"""Doctor checks for FCC default agent runtime scaffolding."""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

from cli.bootstrap_context import (
    HOOK_SCRIPT_NAMES,
    STATUSLINE_SCRIPT_NAMES,
    BootstrapError,
    guard_duplicate_hook_owners,
)

RUNTIME_CONTRACT_RELATIVE = Path(".fcc") / "context" / "agent-runtime.md"
PLUGIN_POLICY_RELATIVE = Path(".fcc") / "plugin-policy.yml"
AGENT_RELATIVES = (
    Path(".claude") / "agents" / "fcc-context-auditor.md",
    Path(".claude") / "agents" / "fcc-code-reviewer.md",
    Path(".claude") / "agents" / "fcc-product-logic-reviewer.md",
    Path(".claude") / "agents" / "fcc-researcher.md",
)
HOOK_RELATIVES = tuple(Path("scripts") / "hooks" / name for name in HOOK_SCRIPT_NAMES)
STATUSLINE_RELATIVES = tuple(
    Path("scripts") / "statusline" / name for name in STATUSLINE_SCRIPT_NAMES
)
SUPPORTED_REQUIRED_HOOKS = (
    "SessionStart",
    "UserPromptSubmit",
    "Stop",
    "PreCompact",
    "SubagentStop",
)


@dataclass(slots=True)
class AgentRuntimeDoctorReport:
    runtime_contract_exists: bool
    plugin_policy_exists: bool
    agent_definitions_present: bool
    hook_scripts_present: bool
    statusline_script_present: bool
    supported_hooks_configured: bool
    duplicate_hook_owners: bool
    memory_owner_valid: bool
    token_savior_baseline: bool
    ralph_loop_policy_valid: bool
    autofixed: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "runtime_contract_exists": self.runtime_contract_exists,
            "plugin_policy_exists": self.plugin_policy_exists,
            "agent_definitions_present": self.agent_definitions_present,
            "hook_scripts_present": self.hook_scripts_present,
            "statusline_script_present": self.statusline_script_present,
            "supported_hooks_configured": self.supported_hooks_configured,
            "duplicate_hook_owners": self.duplicate_hook_owners,
            "memory_owner_valid": self.memory_owner_valid,
            "token_savior_baseline": self.token_savior_baseline,
            "ralph_loop_policy_valid": self.ralph_loop_policy_valid,
            "autofixed": self.autofixed,
            "issues": self.issues,
        }


def run_agent_runtime_doctor(
    project_root: Path,
    *,
    autofix: bool = True,
) -> dict[str, Any]:
    """Check and safely repair FCC runtime contract defaults."""
    root = project_root.expanduser().resolve()
    autofixed: list[str] = []
    if autofix:
        autofixed.extend(_copy_missing_runtime_files(root))

    settings_path = root / ".claude" / "settings.json"
    duplicate_hook_owners = False
    issues: list[str] = []
    try:
        guard_duplicate_hook_owners(settings_path)
    except BootstrapError as exc:
        duplicate_hook_owners = True
        issues.append(str(exc))

    settings = _read_json(settings_path)
    hooks = settings.get("hooks") if isinstance(settings, dict) else None
    supported_hooks_configured = _hooks_configured(hooks)
    if not supported_hooks_configured:
        issues.append("Missing one or more FCC supported hooks.")
    hook_scripts_present = all((root / rel).is_file() for rel in HOOK_RELATIVES)
    statusline_script_present = all(
        (root / rel).is_file() for rel in STATUSLINE_RELATIVES
    )
    if not hook_scripts_present:
        issues.append("Missing one or more FCC hook script files.")
    if not statusline_script_present:
        issues.append("Missing one or more FCC statusline script files.")

    policy_text = _read_text(root / PLUGIN_POLICY_RELATIVE)
    policy_no_comments = _strip_yaml_comments(policy_text)
    memory_owner_valid = _memory_owner_valid(policy_no_comments)
    token_savior_baseline = _token_savior_baseline(policy_no_comments)
    ralph_loop_policy_valid = _ralph_loop_policy_valid(policy_no_comments)
    if not memory_owner_valid:
        issues.append("MemSearch must be the only default persistent memory owner.")
    if not token_savior_baseline:
        issues.append("Token Savior must be the default code-retrieval owner.")
    if not ralph_loop_policy_valid:
        issues.append("Ralph Loop policy must require bounded verified iterations.")

    graph_issues = _check_graph_health(root)
    issues.extend(graph_issues)

    report = AgentRuntimeDoctorReport(
        runtime_contract_exists=(root / RUNTIME_CONTRACT_RELATIVE).is_file(),
        plugin_policy_exists=(root / PLUGIN_POLICY_RELATIVE).is_file(),
        agent_definitions_present=all(
            (root / rel).is_file() for rel in AGENT_RELATIVES
        ),
        hook_scripts_present=hook_scripts_present,
        statusline_script_present=statusline_script_present,
        supported_hooks_configured=supported_hooks_configured,
        duplicate_hook_owners=duplicate_hook_owners,
        memory_owner_valid=memory_owner_valid,
        token_savior_baseline=token_savior_baseline,
        ralph_loop_policy_valid=ralph_loop_policy_valid,
        autofixed=autofixed,
        issues=issues,
    )
    return report.as_dict()


def _check_graph_health(root: Path) -> list[str]:
    """Check knowledge graph health. Returns issues found."""
    graph_json = root / ".fcc" / "graph" / "graph.json"
    if not graph_json.is_file():
        return [
            "No knowledge graph found. Run: fcc-bootstrap-context --install-graphify"
        ]
    size_mb = graph_json.stat().st_size / (1024 * 1024)
    if size_mb > 50:
        return [
            f"graph.json is {size_mb:.0f}MB — may cause slow loads."
        ]
    return []


def _copy_missing_runtime_files(project_root: Path) -> list[str]:
    template_root = _template_root()
    hook_root = _hook_source_root()
    statusline_root = _statusline_source_root()
    copied: list[str] = []
    for rel_path in (
        RUNTIME_CONTRACT_RELATIVE,
        PLUGIN_POLICY_RELATIVE,
        *AGENT_RELATIVES,
    ):
        _copy_missing_resource_file(
            template_root,
            rel_path,
            project_root / rel_path,
            copied,
        )
    for name in HOOK_SCRIPT_NAMES:
        rel_path = Path("scripts") / "hooks" / name
        _copy_missing_resource_file(
            hook_root,
            Path(name),
            project_root / rel_path,
            copied,
            copied_label=rel_path,
        )
    for name in STATUSLINE_SCRIPT_NAMES:
        rel_path = Path("scripts") / "statusline" / name
        _copy_missing_resource_file(
            statusline_root,
            Path(name),
            project_root / rel_path,
            copied,
            copied_label=rel_path,
        )
    return copied


def _copy_missing_resource_file(
    source_root: Any,
    source_rel_path: Path,
    destination: Path,
    copied: list[str],
    *,
    copied_label: Path | None = None,
) -> None:
    source = _join_resource_path(source_root, source_rel_path)
    if destination.exists() or not source.is_file():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(source, Path):
        shutil.copyfile(source, destination)
    else:
        destination.write_bytes(source.read_bytes())
    copied.append((copied_label or source_rel_path).as_posix())


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


def _statusline_source_root() -> Any:
    source = Path(__file__).resolve().parents[1] / "scripts" / "statusline"
    if source.is_dir():
        return source
    return resources.files("cli").joinpath("context_statusline")


def _join_resource_path(root: Any, rel_path: Path) -> Any:
    current = root
    for part in rel_path.parts:
        current = current.joinpath(part)
    return current


def _hooks_configured(hooks: Any) -> bool:
    if not isinstance(hooks, dict):
        return False
    return all(
        event in hooks and _commands_from_hook_entries(hooks[event])
        for event in SUPPORTED_REQUIRED_HOOKS
    )


def _commands_from_hook_entries(node: Any) -> list[str]:
    commands: list[str] = []
    if isinstance(node, list):
        for item in node:
            commands.extend(_commands_from_hook_entries(item))
    elif isinstance(node, dict):
        command = node.get("command")
        if isinstance(command, str):
            commands.append(command)
        nested = node.get("hooks")
        if nested is not None:
            commands.extend(_commands_from_hook_entries(nested))
    return commands


def _memory_owner_valid(policy_text: str) -> bool:
    return (
        "persistent_memory: MemSearch" in policy_text
        and "persistent_memory: Claude-mem" not in policy_text
    )


def _token_savior_baseline(policy_text: str) -> bool:
    return "code_retrieval: Token Savior" in policy_text


def _ralph_loop_policy_valid(policy_text: str) -> bool:
    block = _plugin_block(policy_text, "ralph-loop")
    if not block:
        return True
    if not _bool_field(block, "enabled"):
        return True
    max_iterations = _int_field(block, "max_iterations")
    return (
        max_iterations is not None
        and max_iterations > 0
        and _bool_field(block, "completion_criteria_required")
        and _bool_field(block, "verification_required")
    )


def _plugin_block(policy_text: str, plugin_name: str) -> str:
    lines = policy_text.splitlines()
    for index, line in enumerate(lines):
        if line.strip() != f"{plugin_name}:":
            continue
        indent = len(line) - len(line.lstrip(" "))
        body: list[str] = []
        for child in lines[index + 1 :]:
            child_indent = len(child) - len(child.lstrip(" "))
            if child.strip() and child_indent <= indent:
                break
            body.append(child)
        return "\n".join(body)
    return ""


def _bool_field(block: str, field_name: str) -> bool:
    match = re.search(
        rf"^\s+{re.escape(field_name)}:\s*(true|false)\s*$", block, re.MULTILINE
    )
    return match is not None and match.group(1) == "true"


def _int_field(block: str, field_name: str) -> int | None:
    match = re.search(rf"^\s+{re.escape(field_name)}:\s*(\d+)\s*$", block, re.MULTILINE)
    if match is None:
        return None
    return int(match.group(1))


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if isinstance(data, dict):
        return data
    return {}


def _read_text(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _strip_yaml_comments(text: str) -> str:
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        lines.append(line.split("#", 1)[0].rstrip())
    return "\n".join(lines)
