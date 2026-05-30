"""Bootstrap reusable FCC context, memory, and workflow scaffolding."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

DEFAULT_MEMORY_OWNER = "MemSearch"
DEFAULT_CODE_RETRIEVAL_OWNER = "Token Savior"
TOKEN_SAVIOR_SERVER_NAME = "token-savior"
CLAUDE_CONTEXT_SERVER_NAME = "claude-context"
PROTECTED_TEMPLATE_PATHS = frozenset(
    {
        ".claude/settings.json",
        ".mcp.json",
        ".fcc/plugin-policy.yml",
        ".fcc/context/agent-runtime.md",
        ".fcc/context/facts.md",
        ".fcc/context/decisions.md",
        ".fcc/context/handoff.md",
    }
)

TEMPLATE_REQUIRED_FILES = (
    "CLAUDE.md",
    "CLAUDE.local.example.md",
    ".claude/settings.json",
    ".claude/agents/fcc-context-auditor.md",
    ".claude/agents/fcc-code-reviewer.md",
    ".claude/agents/fcc-product-logic-reviewer.md",
    ".claude/agents/fcc-researcher.md",
    ".claude/commands/handoff.md",
    ".claude/commands/recall.md",
    ".claude/commands/verify-context.md",
    ".claude/skills/context-recall/SKILL.md",
    ".claude/skills/handoff-writer/SKILL.md",
    ".claude/skills/route-task/SKILL.md",
    ".mcp.json",
    ".fcc/plugin-policy.yml",
    ".fcc/context/agent-runtime.md",
    ".fcc/context/facts.md",
    ".fcc/context/decisions.md",
    ".fcc/context/handoff.md",
    ".fcc/router.yml",
    ".fcc/indexes/.gitkeep",
    ".fcc/memory/.gitkeep",
)

HOOK_SCRIPT_NAMES = (
    "_shared.py",
    "session_start.py",
    "user_prompt_submit.py",
    "stop.py",
    "subagent_stop.py",
    "precompact.py",
)

HOOK_OWNER_MARKERS = {
    "FCC context": (
        "scripts/hooks/session_start.py",
        "scripts\\hooks\\session_start.py",
        "scripts/hooks/user_prompt_submit.py",
        "scripts\\hooks\\user_prompt_submit.py",
        "scripts/hooks/stop.py",
        "scripts\\hooks\\stop.py",
        "scripts/hooks/subagent_stop.py",
        "scripts\\hooks\\subagent_stop.py",
        "scripts/hooks/precompact.py",
        "scripts\\hooks\\precompact.py",
        "fcc handoff",
    ),
    "MemSearch": ("memsearch", ".memsearch"),
    "Claude-mem": ("claude-mem", "claude_mem", ".claude-mem"),
    "Claude Context": ("claude-context", "claude_context", "@zilliz/claude-context"),
    "context-mode": ("context-mode", "context_mode"),
}

MEMORY_OWNERS = {"memsearch", "claude-mem"}


class BootstrapError(RuntimeError):
    """Actionable bootstrap failure."""


@dataclass
class BootstrapReport:
    copied: list[Path] = field(default_factory=list)
    skipped: list[Path] = field(default_factory=list)
    modified: list[Path] = field(default_factory=list)
    installed: list[str] = field(default_factory=list)


def bootstrap_context(
    target: Path,
    *,
    force: bool = False,
    install_token_savior: bool = False,
    install_memsearch: bool = False,
    large_repo: bool = False,
) -> BootstrapReport:
    """Copy the project template and optional baseline tool config."""
    root = target.resolve()
    guard_project_hook_owners(root)
    if install_memsearch:
        ensure_single_memory_owner((DEFAULT_MEMORY_OWNER,))
        _fail_if_owner_present(root, "Claude-mem")

    report = BootstrapReport()
    _copy_tree(_template_root(), root, force=force, report=report)
    ensure_claude_settings(root / ".claude" / "settings.json", force=force)
    report.modified.append(root / ".claude" / "settings.json")
    ensure_token_savior_mcp(root / ".mcp.json", force=force)
    report.modified.append(root / ".mcp.json")
    _copy_tree(
        _hook_source_root(),
        root / "scripts" / "hooks",
        force=force,
        report=report,
    )
    _ensure_local_claude(root, force=force, report=report)

    if install_token_savior:
        _run_tool_install(
            [
                "uvx",
                "--from",
                "token-savior-recall==4.4.1",
                "token-savior",
                "--help",
            ],
            "Token Savior",
        )
        report.installed.append("Token Savior")

    if install_memsearch:
        _run_tool_install(
            ["uv", "tool", "install", "--upgrade", "memsearch[onnx]"], "MemSearch"
        )
        memory_dir = root / ".memsearch" / "memory"
        memory_dir.mkdir(parents=True, exist_ok=True)
        gitkeep = memory_dir / ".gitkeep"
        if not gitkeep.exists():
            gitkeep.write_text("", encoding="utf-8")
            report.copied.append(gitkeep)
        report.installed.append("MemSearch")

    if large_repo:
        ensure_claude_context_mcp(root / ".mcp.json", force=force)
        report.modified.append(root / ".mcp.json")

    return report


def guard_duplicate_hook_owners(settings_path: Path) -> None:
    """Fail when a settings file already mixes known hook owners per event."""
    if not settings_path.is_file():
        return
    settings = _load_json(settings_path)
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return

    conflicts: list[str] = []
    for event_name, entries in hooks.items():
        owners = _owners_for_hook_entries(entries)
        if len(owners) > 1:
            joined = ", ".join(sorted(owners))
            conflicts.append(f"{event_name}: {joined}")

    if conflicts:
        raise BootstrapError(
            "Duplicate hook owners detected. Keep one owner per hook event before "
            f"bootstrapping: {'; '.join(conflicts)}"
        )


def guard_project_hook_owners(root: Path) -> None:
    """Fail when existing project hooks conflict with FCC-owned hooks."""
    settings_paths = [
        root / ".claude" / "settings.json",
        root / ".claude" / "settings.local.json",
    ]
    for settings_path in settings_paths:
        guard_duplicate_hook_owners(settings_path)

    existing_events: dict[str, set[str]] = {}
    existing_unknown_commands: dict[str, list[str]] = {}
    for settings_path in settings_paths:
        if not settings_path.is_file():
            continue
        hooks = _load_json(settings_path).get("hooks")
        if not isinstance(hooks, dict):
            continue
        for event_name, entries in hooks.items():
            event = str(event_name)
            commands = _commands_from_hooks(entries)
            owners = {_owner_for_command(command) for command in commands}
            known_owners = {owner for owner in owners if owner is not None}
            if known_owners:
                existing_events.setdefault(event, set()).update(known_owners)
            unknown = [
                command for command in commands if _owner_for_command(command) is None
            ]
            if unknown:
                existing_unknown_commands.setdefault(event, []).extend(unknown)

    fcc_hooks = _template_claude_settings().get("hooks", {})
    if not isinstance(fcc_hooks, dict):
        return
    conflicts: list[str] = []
    for event_name, entries in fcc_hooks.items():
        event = str(event_name)
        fcc_owners = _owners_for_hook_entries(entries)
        existing_owners = existing_events.get(event, set())
        unknown_commands = existing_unknown_commands.get(event, [])
        non_fcc_owners = existing_owners - {"FCC context"}
        if non_fcc_owners:
            joined = ", ".join(sorted(non_fcc_owners | fcc_owners))
            conflicts.append(f"{event}: {joined}")
        elif unknown_commands:
            conflicts.append(f"{event}: existing custom hook plus FCC context")

    if conflicts:
        raise BootstrapError(
            "Existing hook commands would conflict with FCC context hooks. "
            "Keep one owner per hook event before bootstrapping: "
            + "; ".join(conflicts)
        )


def ensure_single_memory_owner(selected: Iterable[str]) -> None:
    """Enforce MemSearch vs Claude-mem mutual exclusion for defaults."""
    normalized = {
        owner.strip().lower()
        for owner in selected
        if owner.strip().lower() in MEMORY_OWNERS
    }
    if {"memsearch", "claude-mem"}.issubset(normalized):
        raise BootstrapError(
            "MemSearch and Claude-mem cannot both be selected as default memory owners."
        )


def ensure_token_savior_mcp(path: Path, *, force: bool) -> None:
    """Add the baseline Token Savior MCP server config."""
    _merge_mcp_server(
        path, TOKEN_SAVIOR_SERVER_NAME, _token_savior_server(), force=force
    )


def ensure_claude_context_mcp(path: Path, *, force: bool) -> None:
    """Add optional Claude Context MCP only for large-repo bootstraps."""
    _merge_mcp_server(
        path,
        CLAUDE_CONTEXT_SERVER_NAME,
        {
            "command": "npx",
            "args": ["-y", "@zilliz/claude-context-mcp@latest"],
            "env": {
                "EMBEDDING_PROVIDER": "Ollama",
                "EMBEDDING_MODEL": "nomic-embed-text",
                "OLLAMA_HOST": "http://127.0.0.1:11434",
                "MILVUS_TOKEN": "${MILVUS_TOKEN:-}",
            },
        },
        force=force,
    )


def ensure_claude_settings(path: Path, *, force: bool) -> None:
    """Merge FCC hook/env settings without dropping existing Claude settings."""
    existing = _load_json(path) if path.is_file() else {}
    template = _template_claude_settings()

    env = existing.setdefault("env", {})
    if not isinstance(env, dict):
        raise BootstrapError(f"{path} has a non-object env value.")
    template_env = template.get("env", {})
    if isinstance(template_env, dict):
        for key, value in template_env.items():
            if force or key not in env:
                env[key] = value

    hooks = existing.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise BootstrapError(f"{path} has a non-object hooks value.")
    template_hooks = template.get("hooks", {})
    if isinstance(template_hooks, dict):
        for event_name, template_entries in template_hooks.items():
            event = str(event_name)
            current_entries = hooks.setdefault(event, [])
            if not isinstance(current_entries, list):
                raise BootstrapError(f"{path} hooks.{event} must be a list.")
            if "FCC context" not in _owners_for_hook_entries(current_entries):
                current_entries.extend(template_entries)
            elif force:
                _replace_fcc_hooks(current_entries, template_entries)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(existing, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def check_template() -> list[str]:
    """Return missing required template files."""
    template_root = _template_root()
    missing = [
        rel_path
        for rel_path in TEMPLATE_REQUIRED_FILES
        if not _join_resource_path(template_root, rel_path).is_file()
    ]
    hook_root = _hook_source_root()
    missing.extend(
        f"scripts/hooks/{name}"
        for name in HOOK_SCRIPT_NAMES
        if not hook_root.joinpath(name).is_file()
    )
    return missing


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Bootstrap FCC context/memory scaffolding into the current repo.",
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=Path.cwd(),
        help="Repository root to bootstrap. Defaults to the current directory.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite non-empty files when copying template files.",
    )
    parser.add_argument(
        "--install-token-savior",
        action="store_true",
        help="Configure and prefetch the baseline Token Savior MCP server.",
    )
    parser.add_argument(
        "--install-memsearch",
        action="store_true",
        help="Install the baseline MemSearch CLI and create its memory directory.",
    )
    parser.add_argument(
        "--large-repo",
        action="store_true",
        help="Also add optional Claude Context MCP for large repositories.",
    )
    parser.add_argument(
        "--check-template",
        action="store_true",
        help="Validate that the packaged bootstrap template is complete.",
    )
    args = parser.parse_args(argv)

    if args.check_template:
        missing = check_template()
        if missing:
            print("Missing template files:", ", ".join(missing), file=sys.stderr)
            raise SystemExit(1)
        print("Template files present.")
        return

    try:
        report = bootstrap_context(
            args.target,
            force=args.force,
            install_token_savior=args.install_token_savior,
            install_memsearch=args.install_memsearch,
            large_repo=args.large_repo,
        )
    except BootstrapError as exc:
        print(f"fcc-bootstrap-context: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    print(f"Copied: {len(report.copied)}")
    print(f"Skipped: {len(report.skipped)}")
    print(f"Modified: {len(report.modified)}")
    if report.installed:
        print("Installed: " + ", ".join(report.installed))


def _template_root() -> Any:
    source = Path(__file__).resolve().parents[1] / "templates" / "project"
    if source.is_dir():
        return source
    return resources.files("cli").joinpath("context_template")


def _hook_source_root() -> Any:
    source = Path(__file__).resolve().parents[1] / "scripts" / "hooks"
    if source.is_dir():
        return source
    return resources.files("cli").joinpath("context_hooks")


def _copy_tree(
    source: Any,
    target: Path,
    *,
    force: bool,
    report: BootstrapReport,
) -> None:
    for child in source.iterdir():
        if child.name == "__pycache__" or child.name.endswith(".pyc"):
            continue
        destination = target / child.name
        if child.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
            _copy_tree(child, destination, force=force, report=report)
            continue
        _copy_file(child, destination, force=force, report=report)


def _join_resource_path(root: Any, rel_path: str) -> Any:
    current = root
    for part in Path(rel_path).parts:
        current = current.joinpath(part)
    return current


def _copy_file(
    source: Any, destination: Path, *, force: bool, report: BootstrapReport
) -> None:
    if _is_protected_template_destination(destination) and destination.exists():
        report.skipped.append(destination)
        return
    if destination.exists() and destination.stat().st_size > 0 and not force:
        report.skipped.append(destination)
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(source.read_bytes())
    report.copied.append(destination)


def _ensure_local_claude(root: Path, *, force: bool, report: BootstrapReport) -> None:
    local_path = root / "CLAUDE.local.md"
    example_path = root / "CLAUDE.local.example.md"
    if not local_path.exists() and example_path.is_file():
        shutil.copyfile(example_path, local_path)
        report.copied.append(local_path)
    elif local_path.exists():
        report.skipped.append(local_path)
    _append_gitignore(root / ".gitignore", "CLAUDE.local.md", report=report)


def _is_protected_template_destination(destination: Path) -> bool:
    normalized = destination.as_posix()
    return any(normalized.endswith(path) for path in PROTECTED_TEMPLATE_PATHS)


def _append_gitignore(path: Path, line: str, *, report: BootstrapReport) -> None:
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    lines = {item.strip() for item in existing.splitlines()}
    if line in lines:
        return
    prefix = "" if existing.endswith("\n") or not existing else "\n"
    path.write_text(f"{existing}{prefix}{line}\n", encoding="utf-8")
    report.modified.append(path)


def _owners_for_hook_entries(entries: Any) -> set[str]:
    commands = _commands_from_hooks(entries)
    owners: set[str] = set()
    for command in commands:
        owner = _owner_for_command(command)
        if owner is not None:
            owners.add(owner)
    return owners


def _replace_fcc_hooks(
    entries: list[dict[str, Any]], template_entries: list[dict[str, Any]]
) -> None:
    """Replace FCC-owned hook entries in-place with current template entries."""
    indices_to_remove: list[int] = []
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        if "hooks" in entry and isinstance(entry["hooks"], list):
            _replace_fcc_hooks(entry["hooks"], template_entries)
        owners = _owners_for_hook_entries([entry])
        if "FCC context" in owners:
            indices_to_remove.append(i)
    for i in reversed(indices_to_remove):
        del entries[i]
    entries.extend(template_entries)


def _commands_from_hooks(node: Any) -> list[str]:
    commands: list[str] = []
    if isinstance(node, list):
        for item in node:
            commands.extend(_commands_from_hooks(item))
    elif isinstance(node, dict):
        command = node.get("command")
        if isinstance(command, str):
            commands.append(command)
        hooks = node.get("hooks")
        if hooks is not None:
            commands.extend(_commands_from_hooks(hooks))
    return commands


def _owner_for_command(command: str) -> str | None:
    lowered = command.lower()
    for owner, markers in HOOK_OWNER_MARKERS.items():
        if any(marker in lowered for marker in markers):
            return owner
    return None


def _load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BootstrapError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise BootstrapError(f"{path} must contain a JSON object.")
    return data


def _template_claude_settings() -> dict[str, Any]:
    settings_path = _join_resource_path(_template_root(), ".claude/settings.json")
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BootstrapError("Template .claude/settings.json is invalid JSON.") from exc
    if not isinstance(data, dict):
        raise BootstrapError("Template .claude/settings.json must be a JSON object.")
    return data


def _merge_mcp_server(
    path: Path,
    name: str,
    server: Mapping[str, Any],
    *,
    force: bool,
) -> None:
    data = _load_json(path) if path.is_file() else {}
    mcp_servers = data.setdefault("mcpServers", {})
    if not isinstance(mcp_servers, dict):
        raise BootstrapError(f"{path} has a non-object mcpServers value.")
    existing = mcp_servers.get(name)
    if existing is not None and existing != server and not force:
        raise BootstrapError(
            f"{name} already exists in {path}. Pass --force to replace it."
        )
    mcp_servers[name] = dict(server)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _token_savior_server() -> dict[str, Any]:
    return {
        "command": "uvx",
        "args": [
            "--from",
            "token-savior-recall==4.4.1",
            "token-savior",
            "server",
        ],
        "env": {
            "WORKSPACE_ROOTS": "${CLAUDE_PROJECT_DIR:-.}",
            "TOKEN_SAVIOR_CLIENT": "claude-code",
            "TOKEN_SAVIOR_PROFILE": "optimized",
        },
    }


def _fail_if_owner_present(root: Path, owner: str) -> None:
    markers = HOOK_OWNER_MARKERS[owner]
    for rel_path in (
        ".claude/settings.json",
        ".claude/settings.local.json",
        ".mcp.json",
    ):
        path = root / rel_path
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace").lower()
        if any(marker in text for marker in markers):
            raise BootstrapError(
                f"{owner} is already configured. MemSearch is the only default "
                "persistent memory owner for this bootstrap."
            )


def _run_tool_install(command: Sequence[str], label: str) -> None:
    try:
        subprocess.run(command, check=True)
    except FileNotFoundError as exc:
        raise BootstrapError(
            f"Could not install {label}: {command[0]} was not found."
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise BootstrapError(
            f"Could not install {label}: command exited {exc.returncode}."
        ) from exc


if __name__ == "__main__":
    main()
