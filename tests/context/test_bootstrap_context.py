from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from cli.bootstrap_context import (
    DEFAULT_CODE_RETRIEVAL_OWNER,
    DEFAULT_MEMORY_OWNER,
    BootstrapError,
    bootstrap_context,
    check_template,
    ensure_single_memory_owner,
    guard_duplicate_hook_owners,
    guard_project_hook_owners,
)
from cli.context_doctor import run_agent_runtime_doctor
from core.context.retrieval import query_index
from core.context.sqlite_store import SQLiteContextStore
from core.context.storage import store_context_output

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOKS_DIR = REPO_ROOT / "scripts" / "hooks"


def load_shared_hooks_module():
    spec = importlib.util.spec_from_file_location(
        "fcc_hook_shared", HOOKS_DIR / "_shared.py"
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def run_hook(script_name: str, payload: dict[str, object]) -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, str(HOOKS_DIR / script_name)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=True,
    )
    output = json.loads(result.stdout)
    assert isinstance(output, dict)
    return output


def hook_command(settings: dict[str, Any], event_name: str) -> str:
    command = settings["hooks"][event_name][0]["hooks"][0]["command"]
    assert isinstance(command, str)
    return command


def write_transcript(path: Path, user_text: str, assistant_text: str) -> None:
    rows = [
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": user_text}],
            },
        },
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": assistant_text}],
            },
        },
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")


def test_template_files_present() -> None:
    assert check_template() == []


def test_bootstrap_copies_template_and_local_file(tmp_path: Path) -> None:
    report = bootstrap_context(tmp_path)

    assert (tmp_path / "CLAUDE.md").is_file()
    assert (tmp_path / "CLAUDE.local.md").is_file()
    assert (tmp_path / ".claude" / "settings.json").is_file()
    assert (tmp_path / ".fcc" / "context" / "agent-runtime.md").is_file()
    assert (tmp_path / ".fcc" / "plugin-policy.yml").is_file()
    assert (tmp_path / ".claude" / "agents" / "fcc-code-reviewer.md").is_file()
    assert (
        tmp_path / ".claude" / "skills" / "claude-command-router" / "SKILL.md"
    ).is_file()
    assert (tmp_path / "scripts" / "hooks" / "session_start.py").is_file()
    assert (tmp_path / "scripts" / "statusline" / "fcc_statusline.py").is_file()
    assert "CLAUDE.local.md" in (tmp_path / ".gitignore").read_text("utf-8")
    assert report.copied


def test_bootstrap_merges_existing_claude_settings(tmp_path: Path) -> None:
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(
        json.dumps({"permissions": {"allow": ["Bash(git status:*)"]}}),
        encoding="utf-8",
    )

    bootstrap_context(tmp_path)

    data = json.loads(settings.read_text("utf-8"))
    assert data["permissions"]["allow"] == ["Bash(git status:*)"]
    assert data["env"]["CLAUDE_CODE_PACKAGE_MANAGER_AUTO_UPDATE"] == "1"
    assert "SessionStart" in data["hooks"]
    assert "scripts/statusline/fcc_statusline.py" in data["statusLine"]["command"]
    assert "Path.cwd().resolve()" in data["statusLine"]["command"]


def test_bootstrap_repairs_legacy_relative_hook_commands(tmp_path: Path) -> None:
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "UserPromptSubmit": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "python scripts/hooks/user_prompt_submit.py",
                                    "timeout": 10,
                                }
                            ]
                        }
                    ]
                },
                "statusLine": {
                    "type": "command",
                    "command": "uv run python scripts/statusline/fcc_statusline.py",
                },
            }
        ),
        encoding="utf-8",
    )

    bootstrap_context(tmp_path)

    data = json.loads(settings.read_text("utf-8"))
    command = hook_command(data, "UserPromptSubmit")
    assert "python scripts/hooks/user_prompt_submit.py" not in command
    assert "scripts/hooks/user_prompt_submit.py" in command
    assert "Path.cwd().resolve()" in command
    assert "Path.cwd().resolve()" in data["statusLine"]["command"]


def test_bootstrapped_hook_command_runs_from_nested_cwd(tmp_path: Path) -> None:
    bootstrap_context(tmp_path)
    nested = tmp_path / "temp"
    nested.mkdir()
    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text("utf-8"))
    command = hook_command(settings, "SessionStart")
    env = {**os.environ, "AUTO_PROMPT_ENHANCER": "false"}

    result = subprocess.run(
        command,
        input=json.dumps({"cwd": str(nested)}),
        text=True,
        capture_output=True,
        shell=True,
        cwd=nested,
        env=env,
        check=True,
    )

    output = json.loads(result.stdout)
    context = output["hookSpecificOutput"]["additionalContext"]
    assert "FCC Agent Runtime" in context
    assert str(nested / "scripts" / "hooks") not in result.stderr


def test_bootstrap_rewrites_every_fcc_hook_command_to_parent_search(
    tmp_path: Path,
) -> None:
    bootstrap_context(tmp_path)

    data = json.loads((tmp_path / ".claude" / "settings.json").read_text("utf-8"))
    for event_name in ("SessionStart", "UserPromptSubmit", "Stop", "PreCompact"):
        command = hook_command(data, event_name)
        assert "Path.cwd().resolve()" in command
        assert "sys.path.insert" in command
        assert "runpy.run_path" in command
    subagent_command = hook_command(data, "SubagentStop")
    assert "scripts/hooks/subagent_stop.py" in subagent_command


def test_bootstrap_parent_search_command_works_when_cwd_has_no_scripts(
    tmp_path: Path,
) -> None:
    bootstrap_context(tmp_path)
    nested = tmp_path / "nested" / "deeper"
    nested.mkdir(parents=True)
    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text("utf-8"))
    command = hook_command(settings, "UserPromptSubmit")
    env = {**os.environ, "AUTO_PROMPT_ENHANCER": "false"}

    result = subprocess.run(
        command,
        input=json.dumps({"cwd": str(nested), "prompt": "please recall handoff"}),
        text=True,
        capture_output=True,
        shell=True,
        cwd=nested,
        env=env,
        check=True,
    )

    output = json.loads(result.stdout)
    assert output["suppressOutput"] is True
    assert "temp/scripts/hooks" not in result.stderr.replace("\\", "/")


def test_bootstrap_replaces_duplicate_legacy_fcc_hooks_without_duplication(
    tmp_path: Path,
) -> None:
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "Stop": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "python scripts/hooks/stop.py",
                                }
                            ]
                        },
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "uv run python scripts/hooks/stop.py",
                                }
                            ]
                        },
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    bootstrap_context(tmp_path)

    data = json.loads(settings.read_text("utf-8"))
    commands = [
        command
        for entry in data["hooks"]["Stop"]
        for command in json.loads(json.dumps(entry)).get("hooks", [])
    ]
    rendered = json.dumps(data["hooks"]["Stop"])
    assert rendered.count("scripts/hooks/stop.py") == 1
    assert "Path.cwd().resolve()" in rendered
    assert len(commands) == 1


def test_hook_project_root_uses_nearest_scaffold_parent(tmp_path: Path) -> None:
    shared = load_shared_hooks_module()
    bootstrap_context(tmp_path)
    nested = tmp_path / "temp" / "screenshots"
    nested.mkdir(parents=True)

    root = shared.project_root({"cwd": str(nested)})

    assert root == tmp_path.resolve()


def test_hook_project_root_prefers_claude_project_dir_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared = load_shared_hooks_module()
    env_root = tmp_path / "env-root"
    payload_root = tmp_path / "payload-root"
    bootstrap_context(env_root)
    bootstrap_context(payload_root)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(env_root))

    root = shared.project_root({"cwd": str(payload_root)})

    assert root == env_root.resolve()


def test_hook_project_root_accepts_file_payload_path(tmp_path: Path) -> None:
    shared = load_shared_hooks_module()
    bootstrap_context(tmp_path)
    file_path = tmp_path / "temp" / "query.sql"
    file_path.parent.mkdir()
    file_path.write_text("select 1", encoding="utf-8")

    root = shared.project_root({"cwd": str(file_path)})

    assert root == tmp_path.resolve()


def test_hook_project_root_does_not_escape_to_home_fcc(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared = load_shared_hooks_module()
    fake_home = tmp_path / "home"
    work = fake_home / "work" / "unbootstrapped"
    (fake_home / ".fcc" / "context").mkdir(parents=True)
    work.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    root = shared.nearest_project_root(work)

    assert root == work.resolve()


def test_context_doctor_autofixes_missing_hook_scripts(tmp_path: Path) -> None:
    bootstrap_context(tmp_path)
    hook_script = tmp_path / "scripts" / "hooks" / "user_prompt_submit.py"
    statusline_script = tmp_path / "scripts" / "statusline" / "fcc_statusline.py"
    hook_script.unlink()
    statusline_script.unlink()

    report = run_agent_runtime_doctor(tmp_path)

    assert hook_script.is_file()
    assert statusline_script.is_file()
    assert report["hook_scripts_present"] is True
    assert report["statusline_script_present"] is True
    assert "scripts/hooks/user_prompt_submit.py" in report["autofixed"]


def test_context_doctor_reports_missing_hook_scripts_without_autofix(
    tmp_path: Path,
) -> None:
    bootstrap_context(tmp_path)
    (tmp_path / "scripts" / "hooks" / "session_start.py").unlink()

    report = run_agent_runtime_doctor(tmp_path, autofix=False)

    assert report["hook_scripts_present"] is False
    assert "Missing one or more FCC hook script files." in report["issues"]


def test_context_doctor_reports_missing_statusline_without_autofix(
    tmp_path: Path,
) -> None:
    bootstrap_context(tmp_path)
    (tmp_path / "scripts" / "statusline" / "fcc_statusline.py").unlink()

    report = run_agent_runtime_doctor(tmp_path, autofix=False)

    assert report["statusline_script_present"] is False
    assert "Missing one or more FCC statusline script files." in report["issues"]


def test_context_doctor_autofixes_all_missing_hook_scripts(tmp_path: Path) -> None:
    bootstrap_context(tmp_path)
    for hook_script in (tmp_path / "scripts" / "hooks").glob("*.py"):
        hook_script.unlink()

    report = run_agent_runtime_doctor(tmp_path)

    assert report["hook_scripts_present"] is True
    for name in (
        "_shared.py",
        "session_start.py",
        "user_prompt_submit.py",
        "stop.py",
        "subagent_stop.py",
        "precompact.py",
    ):
        assert (tmp_path / "scripts" / "hooks" / name).is_file()
        assert f"scripts/hooks/{name}" in report["autofixed"]


def test_context_doctor_does_not_overwrite_existing_hook_script(
    tmp_path: Path,
) -> None:
    bootstrap_context(tmp_path)
    hook_script = tmp_path / "scripts" / "hooks" / "user_prompt_submit.py"
    original = hook_script.read_text("utf-8")
    custom = original + "\n# local customization\n"
    hook_script.write_text(custom, encoding="utf-8")

    report = run_agent_runtime_doctor(tmp_path)

    assert hook_script.read_text("utf-8") == custom
    assert "scripts/hooks/user_prompt_submit.py" not in report["autofixed"]


def test_context_doctor_report_exposes_hook_and_statusline_fields(
    tmp_path: Path,
) -> None:
    bootstrap_context(tmp_path)

    report = run_agent_runtime_doctor(tmp_path, autofix=False)

    assert isinstance(report["hook_scripts_present"], bool)
    assert isinstance(report["statusline_script_present"], bool)
    assert report["hook_scripts_present"] is True
    assert report["statusline_script_present"] is True


def test_bootstrap_repair_is_idempotent_for_portable_hooks(tmp_path: Path) -> None:
    bootstrap_context(tmp_path)
    bootstrap_context(tmp_path)

    data = json.loads((tmp_path / ".claude" / "settings.json").read_text("utf-8"))
    rendered = json.dumps(data["hooks"])

    assert rendered.count("scripts/hooks/session_start.py") == 1
    assert rendered.count("scripts/hooks/user_prompt_submit.py") == 1
    assert rendered.count("scripts/hooks/stop.py") == 1
    assert rendered.count("Path.cwd().resolve()") == 5


def test_bootstrap_force_keeps_portable_hooks_single_owner(tmp_path: Path) -> None:
    bootstrap_context(tmp_path)
    bootstrap_context(tmp_path, force=True)

    data = json.loads((tmp_path / ".claude" / "settings.json").read_text("utf-8"))
    rendered = json.dumps(data["hooks"])

    assert rendered.count("scripts/hooks/precompact.py") == 1
    assert rendered.count("scripts/hooks/subagent_stop.py") == 1
    assert "python scripts/hooks/precompact.py" not in rendered


def test_portable_hook_commands_do_not_capture_absolute_project_paths(
    tmp_path: Path,
) -> None:
    bootstrap_context(tmp_path)

    data = json.loads((tmp_path / ".claude" / "settings.json").read_text("utf-8"))
    command = hook_command(data, "UserPromptSubmit")

    assert str(tmp_path) not in command
    assert "next((x for x in [p,*p.parents]" in command
    assert "assert root is not None" in command


def test_session_start_from_nested_cwd_reads_root_handoff(
    tmp_path: Path,
) -> None:
    bootstrap_context(tmp_path)
    handoff = tmp_path / ".fcc" / "context" / "handoff.md"
    handoff.write_text(
        "# FCC Handoff\n\n## Must Not Forget\n- Root handoff sentinel.\n",
        encoding="utf-8",
    )
    nested = tmp_path / "temp" / "scratch"
    nested.mkdir(parents=True)
    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text("utf-8"))
    env = {**os.environ, "AUTO_PROMPT_ENHANCER": "false"}

    result = subprocess.run(
        hook_command(settings, "SessionStart"),
        input=json.dumps({"cwd": str(nested)}),
        text=True,
        capture_output=True,
        shell=True,
        cwd=nested,
        env=env,
        check=True,
    )

    output = json.loads(result.stdout)
    context = output["hookSpecificOutput"]["additionalContext"]
    assert "Root handoff sentinel" in context


def test_bootstrap_merges_token_savior_into_existing_mcp(tmp_path: Path) -> None:
    mcp = tmp_path / ".mcp.json"
    mcp.write_text(
        json.dumps({"mcpServers": {"other": {"command": "other"}}}),
        encoding="utf-8",
    )

    bootstrap_context(tmp_path)

    data = json.loads(mcp.read_text("utf-8"))
    assert data["mcpServers"]["other"]["command"] == "other"
    assert data["mcpServers"]["token-savior"]["command"] == "uvx"


def test_bootstrap_does_not_overwrite_non_empty_files(tmp_path: Path) -> None:
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text("custom rules\n", encoding="utf-8")

    report = bootstrap_context(tmp_path)

    assert claude_md.read_text("utf-8") == "custom rules\n"
    assert claude_md in report.skipped


def test_bootstrap_force_preserves_local_facts_and_context(tmp_path: Path) -> None:
    local_facts = tmp_path / "CLAUDE.local.md"
    local_facts.write_text("- Local GPU server is llama-box.\n", encoding="utf-8")
    context_dir = tmp_path / ".fcc" / "context"
    context_dir.mkdir(parents=True)
    handoff = context_dir / "handoff.md"
    handoff.write_text("# Custom Handoff\n", encoding="utf-8")

    bootstrap_context(tmp_path, force=True)

    assert local_facts.read_text("utf-8") == "- Local GPU server is llama-box.\n"
    assert handoff.read_text("utf-8") == "# Custom Handoff\n"


def test_fact_recall_from_claude_local(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text("- FCC only.\n", encoding="utf-8")
    (tmp_path / "CLAUDE.local.md").write_text(
        "- Local fact: Redis runs on port 6381.\n",
        encoding="utf-8",
    )
    context_dir = tmp_path / ".fcc" / "context"
    context_dir.mkdir(parents=True)
    (context_dir / "agent-runtime.md").write_text(
        "# FCC Agent Runtime\n- Runtime contract injected first.\n",
        encoding="utf-8",
    )
    (context_dir / "handoff.md").write_text(
        "# FCC Handoff\n\n## Must Not Forget\n- Keep MemSearch.\n",
        encoding="utf-8",
    )

    output = run_hook("session_start.py", {"cwd": str(tmp_path)})

    context = output["hookSpecificOutput"]["additionalContext"]
    assert "Runtime contract injected first" in context
    assert "Redis runs on port 6381" in context
    assert "FCC project context" in context


def test_handoff_regeneration_on_stop(tmp_path: Path) -> None:
    context_dir = tmp_path / ".fcc" / "context"
    context_dir.mkdir(parents=True)
    (context_dir / "facts.md").write_text(
        "- Persistent memory owner: MemSearch.\n",
        encoding="utf-8",
    )
    (context_dir / "handoff.md").write_text(
        "# FCC Handoff\n\n## Must Not Forget\n- FCC remains the router.\n",
        encoding="utf-8",
    )
    transcript = tmp_path / "session.jsonl"
    write_transcript(
        transcript,
        "We decided to use SQLite FTS5 for large tool outputs.",
        "Implemented stop hook regeneration and decision capture.",
    )

    output = run_hook(
        "stop.py",
        {"cwd": str(tmp_path), "transcript_path": str(transcript)},
    )

    handoff = (context_dir / "handoff.md").read_text("utf-8")
    decisions = (context_dir / "decisions.md").read_text("utf-8")
    assert output["systemMessage"] == "FCC handoff updated"
    assert "FCC remains the router" in handoff
    assert "SQLite FTS5" in handoff
    assert "SQLite FTS5" in decisions


def test_handoff_regeneration_replaces_temp_file_atomically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared = load_shared_hooks_module()
    context_dir = tmp_path / ".fcc" / "context"
    context_dir.mkdir(parents=True)
    transcript = tmp_path / "session.jsonl"
    write_transcript(transcript, "Fix the queue race.", "Done.")
    calls: list[tuple[Path, Path]] = []
    path_type = type(tmp_path)
    original_replace = path_type.replace

    def record_replace(self: Path, target: Path) -> Path:
        calls.append((self, target))
        return original_replace(self, target)

    monkeypatch.setattr(path_type, "replace", record_replace)

    shared.regenerate_handoff(tmp_path, transcript)

    assert calls
    temp_path, handoff_path = calls[0]
    assert temp_path.name == "handoff.tmp"
    assert handoff_path == context_dir / "handoff.md"
    assert handoff_path.is_file()


def test_precompact_carries_only_must_not_forget(tmp_path: Path) -> None:
    context_dir = tmp_path / ".fcc" / "context"
    context_dir.mkdir(parents=True)
    (context_dir / "handoff.md").write_text(
        "\n".join(
            [
                "# FCC Handoff",
                "",
                "## Must Not Forget",
                "- The billing fixture is local-only.",
                "",
                "## Current State",
                "- This current-state line should not be injected.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    output = run_hook("precompact.py", {"cwd": str(tmp_path)})

    context = output["hookSpecificOutput"]["additionalContext"]
    assert "billing fixture" in context
    assert "current-state line" in context


@pytest.mark.parametrize(
    ("script_name", "payload"),
    [
        ("session_start.py", {}),
        ("user_prompt_submit.py", {"prompt": "please recall the handoff"}),
        ("precompact.py", {}),
        ("subagent_stop.py", {}),
    ],
)
def test_hook_scripts_emit_valid_json(
    tmp_path: Path,
    script_name: str,
    payload: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTO_PROMPT_ENHANCER", "false")
    payload = {"cwd": str(tmp_path), **payload}
    output = run_hook(script_name, payload)

    assert output["suppressOutput"] is True


def test_compact_lines_unmatched_fence_keeps_remaining_context() -> None:
    shared = load_shared_hooks_module()

    result = shared.compact_lines("before\n```\nimportant after")

    assert "before" in result
    assert "important after" in result


def test_user_prompt_enhancement_hook_defaults_enabled_and_reports_missing_proxy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared = load_shared_hooks_module()
    monkeypatch.delenv("AUTO_PROMPT_ENHANCER", raising=False)
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_URL", raising=False)
    monkeypatch.delenv("FCC_PORT", raising=False)

    context, system_message = shared.prompt_enhancement_outputs("fix bug", tmp_path)

    assert context == ""
    assert "no proxy URL" in system_message


def test_user_prompt_enhancement_hook_emits_additional_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.prompt_enhancer import PromptEnhancementResult

    shared = load_shared_hooks_module()
    monkeypatch.setenv("AUTO_PROMPT_ENHANCER", "true")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:8082")
    monkeypatch.setenv("PROMPT_ENHANCER_MODEL", "custom-enhancer-model")
    seen: dict[str, str] = {}

    def fake_enhance(*_args: object, **kwargs: object) -> PromptEnhancementResult:
        seen["model"] = str(kwargs["model"])
        return PromptEnhancementResult(
            original_prompt="fix bug",
            enhanced_prompt="Fix the authentication bug and run the API regression tests.",
            status="enhanced",
        )

    monkeypatch.setattr(shared, "_enhance_prompt_with_core", fake_enhance)

    context = shared.prompt_enhancement_hint("fix bug", tmp_path)

    assert "FCC enhanced prompt" in context
    assert "authentication bug" in context
    assert seen["model"] == "custom-enhancer-model"


def test_user_prompt_enhancement_hook_emits_visible_system_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.prompt_enhancer import PromptEnhancementResult

    shared = load_shared_hooks_module()
    monkeypatch.setenv("AUTO_PROMPT_ENHANCER", "true")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:8082")

    def fake_enhance(*_args: object, **_kwargs: object) -> PromptEnhancementResult:
        return PromptEnhancementResult(
            original_prompt="fix bug",
            enhanced_prompt="Fix the authentication bug and run the API regression tests.",
            status="enhanced",
        )

    monkeypatch.setattr(shared, "_enhance_prompt_with_core", fake_enhance)

    context, system_message = shared.prompt_enhancement_outputs("fix bug", tmp_path)

    assert "authentication bug" in context
    assert system_message.startswith("FCC auto-enhanced prompt:")
    assert "authentication bug" in system_message


def test_user_prompt_enhancement_hook_reports_missing_proxy_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared = load_shared_hooks_module()
    monkeypatch.setenv("AUTO_PROMPT_ENHANCER", "true")
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_URL", raising=False)
    monkeypatch.delenv("FCC_PORT", raising=False)

    context, system_message = shared.prompt_enhancement_outputs("fix bug", tmp_path)

    assert context == ""
    assert "no proxy URL" in system_message


def test_user_prompt_enhancement_hook_uses_fcc_port_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared = load_shared_hooks_module()
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_URL", raising=False)
    monkeypatch.setenv("FCC_PORT", "9099")

    assert shared._messages_api_url() == "http://127.0.0.1:9099/v1/messages"


def test_user_prompt_enhancement_hook_normalizes_v1_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared = load_shared_hooks_module()
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:8082/v1")

    assert shared._messages_api_url() == "http://127.0.0.1:8082/v1/messages"


def test_hook_runtime_error_still_emits_json(tmp_path: Path) -> None:
    (tmp_path / ".fcc").write_text("not a directory", encoding="utf-8")

    output = run_hook("stop.py", {"cwd": str(tmp_path)})

    assert output["suppressOutput"] is True
    assert "hook failed" in output["systemMessage"]


def test_sqlite_retrieval_works(tmp_path: Path) -> None:
    db_path = tmp_path / "context.sqlite"
    store = SQLiteContextStore(db_path)
    handle = store.store_output(
        "pytest failed because the frobnicator timeout was too low",
        kind="terminal",
        source="pytest",
    )

    results = query_index("frobnicator timeout", db_path=db_path)

    assert results
    assert results[0]["handle"] == handle
    assert "frobnicator" in str(results[0]["snippet"])


def test_sqlite_store_cli_helper_works(tmp_path: Path) -> None:
    db_path = tmp_path / "context.sqlite"
    stored = store_context_output(
        "mypy output mentioned contravariant widget adapters",
        kind="terminal",
        source="ty",
        db_path=db_path,
    )

    results = query_index("contravariant widget", db_path=db_path)

    assert stored["handle"] == results[0]["handle"]
    assert isinstance(stored["chars"], int)
    assert stored["chars"] > 0


def test_sqlite_store_cli_writes_handle(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from core.context.storage import main as store_main

    db_path = tmp_path / "context.sqlite"
    content_file = tmp_path / "output.txt"
    content_file.write_text(
        "terminal output with unusual glacier token", encoding="utf-8"
    )

    store_main(
        [
            "--db",
            str(db_path),
            "--file",
            str(content_file),
            "--kind",
            "terminal",
            "--source",
            "pytest",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["handle"]
    assert query_index("glacier", db_path=db_path)[0]["handle"] == payload["handle"]


def test_duplicate_hook_guard_fails_with_helpful_message(tmp_path: Path) -> None:
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {"hooks": [{"type": "command", "command": "memsearch watch"}]},
                        {"hooks": [{"type": "command", "command": "claude-mem start"}]},
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(BootstrapError, match="Duplicate hook owners"):
        guard_duplicate_hook_owners(settings)


def test_settings_local_hook_conflict_blocks_bootstrap(tmp_path: Path) -> None:
    settings = tmp_path / ".claude" / "settings.local.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {"hooks": [{"type": "command", "command": "memsearch watch"}]}
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(BootstrapError, match="would conflict"):
        guard_project_hook_owners(tmp_path)


def test_custom_existing_hook_conflict_blocks_bootstrap(tmp_path: Path) -> None:
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "Stop": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "python scripts/custom_stop.py",
                                }
                            ]
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(BootstrapError, match="custom hook"):
        bootstrap_context(tmp_path)


def test_memsearch_and_claude_mem_defaults_are_mutually_exclusive() -> None:
    assert DEFAULT_MEMORY_OWNER == "MemSearch"
    assert DEFAULT_CODE_RETRIEVAL_OWNER == "Token Savior"
    with pytest.raises(BootstrapError, match="cannot both"):
        ensure_single_memory_owner(("MemSearch", "Claude-mem"))

    template_text = (REPO_ROOT / "templates" / "project" / ".mcp.json").read_text(
        "utf-8"
    )
    assert "claude-mem" not in template_text.lower()


def test_user_prompt_submit_emits_routing_hint_for_large_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTO_PROMPT_ENHANCER", "false")
    output = run_hook(
        "user_prompt_submit.py",
        {
            "cwd": str(tmp_path),
            "prompt": "Review this multi-file change line by line and run tests.",
        },
    )

    context = output["hookSpecificOutput"]["additionalContext"]
    assert "FCC routing hint" in context
    assert "review" in context
    assert "large task" in context


def test_user_prompt_submit_emits_command_protocol_for_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTO_PROMPT_ENHANCER", "false")
    output = run_hook(
        "user_prompt_submit.py",
        {
            "cwd": str(tmp_path),
            "prompt": "The context is too full; should we compact now?",
        },
    )

    context = output["hookSpecificOutput"]["additionalContext"]
    assert "FCC command protocol" in context
    assert "/context all" in context
    assert "/compact" in context


def test_user_prompt_submit_surfaces_auto_enhancer_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTO_PROMPT_ENHANCER", "true")
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_URL", raising=False)
    monkeypatch.delenv("FCC_PORT", raising=False)

    output = run_hook(
        "user_prompt_submit.py",
        {"cwd": str(tmp_path), "prompt": "fix the login bug"},
    )

    assert "no proxy URL" in output["systemMessage"]


def test_user_prompt_submit_skips_protocol_for_explicit_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTO_PROMPT_ENHANCER", "false")
    output = run_hook(
        "user_prompt_submit.py",
        {"cwd": str(tmp_path), "prompt": "/context all"},
    )

    assert "hookSpecificOutput" not in output


def test_session_start_suggests_init_when_project_context_missing(
    tmp_path: Path,
) -> None:
    output = run_hook("session_start.py", {"cwd": str(tmp_path)})

    context = output["hookSpecificOutput"]["additionalContext"]
    assert "FCC command protocol" in context
    assert "/init" in context
    assert "fcc-bootstrap-context" in context


def test_statusline_script_outputs_compact_status(tmp_path: Path) -> None:
    script = REPO_ROOT / "scripts" / "statusline" / "fcc_statusline.py"
    payload = {
        "model": {"display_name": "Sonnet"},
        "workspace": {"current_dir": str(tmp_path)},
        "context_window": {"used_percentage": 42},
    }
    result = subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=True,
    )

    assert result.stdout.strip() == f"FCC | Sonnet | {tmp_path.name} | ctx 42%"


def test_user_prompt_submit_skips_trivial_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTO_PROMPT_ENHANCER", "false")
    output = run_hook(
        "user_prompt_submit.py",
        {"cwd": str(tmp_path), "prompt": "ok thanks"},
    )

    assert "hookSpecificOutput" not in output


def test_subagent_definitions_carry_fcc_runtime_awareness() -> None:
    agents_dir = REPO_ROOT / "templates" / "project" / ".claude" / "agents"
    for agent_path in agents_dir.glob("fcc-*.md"):
        text = agent_path.read_text("utf-8")
        assert "FCC" in text
        assert "description:" in text
        assert "Token Savior" in text or "Ralph Loop" in text or "handoff" in text


def test_context_doctor_autofixes_runtime_files(tmp_path: Path) -> None:
    bootstrap_context(tmp_path)
    for rel_path in (
        Path(".fcc") / "context" / "agent-runtime.md",
        Path(".fcc") / "plugin-policy.yml",
        Path(".claude") / "agents" / "fcc-context-auditor.md",
    ):
        (tmp_path / rel_path).unlink()

    report = run_agent_runtime_doctor(tmp_path)

    assert report["runtime_contract_exists"] is True
    assert report["plugin_policy_exists"] is True
    assert report["agent_definitions_present"] is True
    assert report["supported_hooks_configured"] is True
    assert report["autofixed"]


def test_context_doctor_detects_duplicate_hook_owners(tmp_path: Path) -> None:
    bootstrap_context(tmp_path)
    settings = tmp_path / ".claude" / "settings.json"
    data = json.loads(settings.read_text("utf-8"))
    data["hooks"]["SessionStart"].append(
        {"hooks": [{"type": "command", "command": "memsearch watch"}]}
    )
    settings.write_text(json.dumps(data), encoding="utf-8")

    report = run_agent_runtime_doctor(tmp_path, autofix=False)

    assert report["duplicate_hook_owners"] is True
    assert report["issues"]


def test_context_doctor_detects_bad_memory_policy(tmp_path: Path) -> None:
    bootstrap_context(tmp_path)
    policy = tmp_path / ".fcc" / "plugin-policy.yml"
    policy.write_text(
        policy.read_text("utf-8").replace(
            "persistent_memory: MemSearch",
            "persistent_memory: Claude-mem",
        ),
        encoding="utf-8",
    )

    report = run_agent_runtime_doctor(tmp_path, autofix=False)

    assert report["memory_owner_valid"] is False


def test_ralph_loop_policy_requires_bounded_verification(tmp_path: Path) -> None:
    bootstrap_context(tmp_path)
    policy = tmp_path / ".fcc" / "plugin-policy.yml"
    text = policy.read_text("utf-8")
    policy.write_text(
        text.replace("enabled: false", "enabled: true", 1).replace(
            "max_iterations: 3",
            "max_iterations: 0",
        ),
        encoding="utf-8",
    )

    report = run_agent_runtime_doctor(tmp_path, autofix=False)

    assert report["ralph_loop_policy_valid"] is False


def test_missing_ralph_plugin_does_not_break_context_doctor(tmp_path: Path) -> None:
    bootstrap_context(tmp_path)

    report = run_agent_runtime_doctor(tmp_path, autofix=False)

    assert report["ralph_loop_policy_valid"] is True
    non_graph_issues = [
        i for i in report["issues"] if "knowledge graph" not in i
    ]
    assert non_graph_issues == []


def test_route_policy_uses_fcc_aliases_without_deepseek_names() -> None:
    route_policy = (REPO_ROOT / ".fcc" / "router.yml").read_text("utf-8")
    template_policy = (
        REPO_ROOT / "templates" / "project" / ".fcc" / "router.yml"
    ).read_text("utf-8")

    for policy in (route_policy, template_policy):
        assert "trivial:" in policy
        assert "alias: haiku" in policy
        assert "balanced:" in policy
        assert "alias: sonnet" in policy
        assert "deep:" in policy
        assert "alias: opus" in policy
        assert "deepseek" not in policy.lower()


def test_mcp_template_uses_exact_token_savior_command() -> None:
    data = json.loads((REPO_ROOT / "templates" / "project" / ".mcp.json").read_text())
    server = data["mcpServers"]["token-savior"]

    assert server["command"] == "uvx"
    assert server["args"] == [
        "--from",
        "token-savior-recall==4.4.1",
        "token-savior",
        "server",
    ]
