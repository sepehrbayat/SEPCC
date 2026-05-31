"""CLI entry points for the installed package."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from collections.abc import Mapping, Sequence
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import uvicorn
from loguru import logger

from api.admin_urls import local_admin_url, local_proxy_root_url
from api.app import GracefulLifespanApp, create_app
from cli.claude_runtime import apply_claude_code_runtime_env, maybe_update_claude_code
from cli.process_registry import (
    kill_all_best_effort,
    kill_pid_tree_best_effort,
    register_pid,
    unregister_pid,
)
from cli.session_registry import (
    SessionRegistry,
    discover_latest_transcript,
    resolve_project_root,
)
from cli.session_resume import build_resume_plan, choose_resume_session
from config.paths import config_dir_path, legacy_env_paths, managed_env_path
from config.settings import Settings, get_settings
from core.context.handoff import regenerate_handoff

PROXY_PREFLIGHT_PATH = "/health"
PROXY_PREFLIGHT_TIMEOUT_SECONDS = 1.5
SERVER_GRACEFUL_SHUTDOWN_SECONDS = 5
HEARTBEAT_INTERVAL_SECONDS = 15


def _load_env_template() -> str:
    """Load the canonical root env template from package resources or source."""
    import importlib.resources

    packaged = importlib.resources.files("cli").joinpath("env.example")
    if packaged.is_file():
        return packaged.read_text("utf-8")

    source_template = Path(__file__).resolve().parents[1] / ".env.example"
    if source_template.is_file():
        return source_template.read_text(encoding="utf-8")

    raise FileNotFoundError("Could not find bundled or source .env.example template.")


def serve() -> None:
    """Start the FastAPI server (registered as `fcc-server` script)."""
    opened_admin_browser = False
    try:
        try:
            while True:
                _migrate_legacy_env_if_missing()
                settings = get_settings()
                if not _run_supervised_server(
                    settings, open_admin_browser=not opened_admin_browser
                ):
                    return
                opened_admin_browser = True
                get_settings.cache_clear()
        except KeyboardInterrupt:
            return
    finally:
        kill_all_best_effort()


def _admin_browser_open_enabled() -> bool:
    """Whether to open /admin when the server becomes reachable (FCC_OPEN_BROWSER)."""

    raw = os.environ.get("FCC_OPEN_BROWSER", "true").strip().lower()
    return raw not in {"", "0", "false", "no"}


def _schedule_open_admin_browser(settings: Settings) -> None:
    """After /health succeeds, open the admin UI in the default browser (daemon thread)."""

    if not _admin_browser_open_enabled():
        return

    admin_url = local_admin_url(settings)
    proxy_root_url = local_proxy_root_url(settings)

    def open_when_ready() -> None:
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            if _preflight_proxy(proxy_root_url) is None:
                webbrowser.open(admin_url)
                return
            time.sleep(0.15)

    threading.Thread(
        target=open_when_ready, name="fcc-open-admin-browser", daemon=True
    ).start()


def _run_supervised_server(settings: Settings, *, open_admin_browser: bool) -> bool:
    """Run one uvicorn server instance; return whether admin requested restart."""

    restart_requested = False
    server_holder: dict[str, uvicorn.Server] = {}

    def request_restart() -> None:
        nonlocal restart_requested
        restart_requested = True
        if server := server_holder.get("server"):
            server.should_exit = True

    app = create_app(lifespan_enabled=False)
    app.state.admin_restart_callback = request_restart
    asgi_app = GracefulLifespanApp(app)
    config = uvicorn.Config(
        asgi_app,
        host=settings.host,
        port=settings.port,
        log_level="debug",
        timeout_graceful_shutdown=SERVER_GRACEFUL_SHUTDOWN_SECONDS,
    )
    server = uvicorn.Server(config)
    server_holder["server"] = server
    if open_admin_browser:
        _schedule_open_admin_browser(settings)
    server.run()
    return restart_requested


def init() -> None:
    """Scaffold config at ~/.fcc/.env (registered as `fcc-init`)."""
    config_dir = config_dir_path()
    env_file = managed_env_path()

    migrated_from = _migrate_legacy_env_if_missing()
    if migrated_from is not None:
        print(f"Config migrated from {migrated_from} to {env_file}")
        print(
            "Edit it to set your API keys and model preferences, then run: fcc-server"
        )
        return

    if env_file.exists():
        print(f"Config already exists at {env_file}")
        print("Delete it first if you want to reset to defaults.")
        return

    config_dir.mkdir(parents=True, exist_ok=True)
    template = _load_env_template()
    env_file.write_text(template, encoding="utf-8")
    print(f"Config created at {env_file}")
    print("Edit it to set your API keys and model preferences, then run: fcc-server")


def _migrate_legacy_env_if_missing() -> Path | None:
    """Copy a legacy user env into the managed config path when absent."""

    env_file = managed_env_path()
    if env_file.exists():
        return None

    # TODO: Remove after the ~/.fcc/.env migration has had a release cycle.
    for legacy_env in legacy_env_paths():
        if not legacy_env.is_file():
            continue
        env_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(legacy_env, env_file)
        return legacy_env

    return None


def _claude_child_env(
    settings: Settings, base_env: Mapping[str, str]
) -> dict[str, str]:
    """Return a Claude Code environment that targets this proxy."""

    env = {
        key: value
        for key, value in base_env.items()
        if not key.startswith("ANTHROPIC_")
    }
    env.pop("ANTHROPIC_API_KEY", None)
    env["ANTHROPIC_BASE_URL"] = local_proxy_root_url(settings)
    apply_claude_code_runtime_env(env)
    env["AUTO_PROMPT_ENHANCER"] = "true" if settings.auto_prompt_enhancer else "false"
    env["PROMPT_ENHANCER_MODEL"] = settings.prompt_enhancer_model
    env["PROMPT_ENHANCER_TIMEOUT"] = str(settings.prompt_enhancer_timeout)
    env["PROMPT_ENHANCER_MAX_OUTPUT_CHARS"] = str(
        settings.prompt_enhancer_max_output_chars
    )
    env["FCC_PACKAGE_ROOT"] = str(Path(__file__).resolve().parents[1])
    if token := settings.anthropic_auth_token.strip():
        env["ANTHROPIC_AUTH_TOKEN"] = token
    return env


def _preflight_proxy(proxy_root_url: str) -> str | None:
    """Return an error message when the local proxy health check is unreachable."""

    url = f"{proxy_root_url.rstrip('/')}{PROXY_PREFLIGHT_PATH}"
    request = Request(url, method="GET")
    try:
        with urlopen(request, timeout=PROXY_PREFLIGHT_TIMEOUT_SECONDS) as response:
            status_code = response.getcode()
    except HTTPError as exc:
        return f"returned HTTP {exc.code}"
    except URLError as exc:
        return str(exc.reason)
    except OSError as exc:
        return str(exc)

    if not 200 <= status_code < 300:
        return f"returned HTTP {status_code}"
    return None


def _resolve_launch_workdir(argv: Sequence[str]) -> tuple[Path, list[str]]:
    """If the first argv entry is an existing directory, use it as Claude's workspace."""

    args = list(argv)
    if not args:
        return Path.cwd(), args

    candidate = Path(args[0]).expanduser()
    if candidate.is_dir():
        return candidate.resolve(), args[1:]

    return Path.cwd(), args


def launch_claude(
    argv: Sequence[str] | None = None,
    *,
    resume_ref: str | None = None,
    auto_resume: bool | None = None,
) -> None:
    """Launch Claude Code with SEPCC proxy environment variables."""

    settings = get_settings()
    proxy_root_url = local_proxy_root_url(settings)
    if error := _preflight_proxy(proxy_root_url):
        print(
            f"SEPCC proxy is not reachable at {proxy_root_url}: {error}",
            file=sys.stderr,
        )
        print("Start it in another terminal with: fcc-server", file=sys.stderr)
        raise SystemExit(1)

    raw_args = list(sys.argv[1:] if argv is None else argv)
    work_dir, args = _resolve_launch_workdir(raw_args)
    project_root = resolve_project_root(work_dir)
    registry = SessionRegistry(project_root)
    registry.heal_stale_active_sessions()
    claude_command = shutil.which(settings.claude_cli_bin)
    if claude_command is None:
        print(
            f"Could not find Claude Code command: {settings.claude_cli_bin}",
            file=sys.stderr,
        )
        print(
            "Install Claude Code with: npm install -g @anthropic-ai/claude-code",
            file=sys.stderr,
        )
        raise SystemExit(127)

    maybe_update_claude_code(claude_command)
    resume_plan = None
    if resume_ref is not None:
        selected = choose_resume_session(
            registry,
            explicit_ref=resume_ref,
            max_age_days=_settings_int(settings, "fcc_auto_resume_max_age_days", 7),
            project_scoped=_settings_bool(
                settings, "fcc_auto_resume_project_scoped", True
            ),
            picker_on_ambiguous=False,
        )
        if selected is None:
            raise SystemExit(f"FCC session not found: {resume_ref}")
        resume_plan = build_resume_plan(registry, selected)
    elif _auto_resume_enabled(settings, args, auto_resume=auto_resume):
        selected = choose_resume_session(
            registry,
            explicit_ref=None,
            max_age_days=_settings_int(settings, "fcc_auto_resume_max_age_days", 7),
            project_scoped=_settings_bool(
                settings, "fcc_auto_resume_project_scoped", True
            ),
            picker_on_ambiguous=_settings_bool(
                settings, "fcc_session_picker_on_ambiguous", True
            ),
        )
        resume_plan = build_resume_plan(registry, selected)

    command = [claude_command, "--dangerously-skip-permissions"]
    parent_session_id = None
    native_resume_id = None
    provider, model = _provider_model_for_session(settings, resume_plan)
    if resume_plan is not None and resume_plan.use_native_resume:
        native_resume_id = resume_plan.native_session_id
        command.extend(["--resume", native_resume_id or ""])
    elif resume_plan is not None and resume_plan.continuity_prompt:
        parent_session_id = resume_plan.parent_session_id
        command.extend(["--append-system-prompt", resume_plan.continuity_prompt])
    command.extend(args)
    env = _claude_child_env(settings, os.environ)
    process: subprocess.Popen[bytes] | None = None
    session_record = (
        resume_plan.session
        if resume_plan is not None
        and resume_plan.use_native_resume
        and resume_plan.session is not None
        else registry.create_terminal_session(
            cwd=work_dir,
            command=command,
            provider=provider,
            model=model,
            parent_session_id=parent_session_id,
            native_session_id=native_resume_id,
            metadata={"argv": args, "resume_ref": resume_ref},
        )
    )
    if resume_plan is not None and resume_plan.use_native_resume and session_record:
        registry.update(
            session_record.session_id,
            status="active",
            cwd=str(work_dir),
            command=" ".join(command),
            provider=provider,
            model=model,
        )
    heartbeat_stop = threading.Event()
    return_code: int | None = None
    try:
        process = subprocess.Popen(command, env=env, cwd=str(work_dir))
        if process.pid:
            register_pid(process.pid)
            registry.set_process(session_record.session_id, process.pid)
            _start_session_heartbeat(
                registry, session_record.session_id, heartbeat_stop
            )
        return_code = process.wait()
    except FileNotFoundError:
        print(
            f"Could not find Claude Code command: {settings.claude_cli_bin}",
            file=sys.stderr,
        )
        print(
            "Install Claude Code with: npm install -g @anthropic-ai/claude-code",
            file=sys.stderr,
        )
        raise SystemExit(127) from None
    except KeyboardInterrupt:
        if process is not None and process.pid:
            kill_pid_tree_best_effort(process.pid)
            process.wait()
        return_code = 0
        raise
    finally:
        heartbeat_stop.set()
        try:
            if process is not None and process.pid:
                unregister_pid(process.pid)
            _finish_registered_terminal_session(
                registry,
                session_record.session_id,
                project_root=project_root,
                work_dir=work_dir,
                started_at=session_record.started_at,
                native_session_id=native_resume_id,
                return_code=return_code,
            )
        except Exception:
            logger.exception(
                "Failed to finalize terminal session {}", session_record.session_id
            )

    raise SystemExit(return_code)


def _finish_registered_terminal_session(
    registry: SessionRegistry,
    session_id: str,
    *,
    project_root: Path,
    work_dir: Path,
    started_at: str,
    native_session_id: str | None,
    return_code: int | None,
) -> None:
    transcript = discover_latest_transcript(
        project_root=project_root,
        cwd=work_dir,
        started_at=started_at,
        native_session_id=native_session_id,
    )
    registry.finish_terminal_session(
        session_id,
        return_code=return_code,
        transcript=transcript,
    )
    if transcript is not None:
        try:
            regenerate_handoff(project_root, transcript.path)
        except OSError:
            return


def _start_session_heartbeat(
    registry: SessionRegistry,
    session_id: str,
    stop_event: threading.Event,
) -> None:
    def heartbeat() -> None:
        while not stop_event.wait(HEARTBEAT_INTERVAL_SECONDS):
            try:
                registry.heartbeat(session_id)
            except Exception:
                logger.exception("Heartbeat failed for session {}", session_id)

    threading.Thread(
        target=heartbeat,
        name=f"fcc-session-heartbeat-{session_id}",
        daemon=True,
    ).start()


def _auto_resume_enabled(
    settings: Settings,
    args: list[str],
    *,
    auto_resume: bool | None,
) -> bool:
    if auto_resume is not None:
        return auto_resume
    if not _settings_bool(settings, "fcc_auto_resume_last_session", True):
        return False
    if args:
        return False
    return not _args_request_native_resume(args)


def _args_request_native_resume(args: list[str]) -> bool:
    native_resume_flags = {
        "--resume",
        "-r",
        "--continue",
        "-c",
        "--session-id",
        "--no-session-persistence",
    }
    return any(
        arg in native_resume_flags
        or any(arg.startswith(f"{flag}=") for flag in native_resume_flags)
        for arg in args
    )


def _settings_bool(settings: Settings, name: str, default: bool) -> bool:
    value = getattr(settings, name, default)
    return bool(value)


def _settings_int(settings: Settings, name: str, default: int) -> int:
    value = getattr(settings, name, default)
    try:
        return int(value)
    except TypeError:
        return default


def _provider_model_for_session(
    settings: Settings,
    resume_plan: object | None,
) -> tuple[str, str]:
    session = getattr(resume_plan, "session", None)
    session_provider = getattr(session, "provider", None)
    session_model = getattr(session, "model", None)
    model = session_model or settings.model
    provider = session_provider or Settings.parse_provider_type(model)
    return str(provider), str(model)
