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

    report = AgentRuntimeDoctorReport(
        runtime_contract_exists=(root / RUNTIME_CONTRACT_RELATIVE).is_file(),
        plugin_policy_exists=(root / PLUGIN_POLICY_RELATIVE).is_file(),
        agent_definitions_present=all(
            (root / rel).is_file() for rel in AGENT_RELATIVES
        ),
        supported_hooks_configured=supported_hooks_configured,
        duplicate_hook_owners=duplicate_hook_owners,
        memory_owner_valid=memory_owner_valid,
        token_savior_baseline=token_savior_baseline,
        ralph_loop_policy_valid=ralph_loop_policy_valid,
        autofixed=autofixed,
        issues=issues,
    )
    return report.as_dict()


def _copy_missing_runtime_files(project_root: Path) -> list[str]:
    template_root = _template_root()
    copied: list[str] = []
    rel_paths = (RUNTIME_CONTRACT_RELATIVE, PLUGIN_POLICY_RELATIVE, *AGENT_RELATIVES)
    for rel_path in rel_paths:
        source = _join_resource_path(template_root, rel_path)
        destination = project_root / rel_path
        if destination.exists() or not source.is_file():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(source, Path):
            shutil.copyfile(source, destination)
        else:
            destination.write_bytes(source.read_bytes())
        copied.append(rel_path.as_posix())
    return copied


def _template_root() -> Any:
    source = Path(__file__).resolve().parents[1] / "templates" / "project"
    if source.is_dir():
        return source
    return resources.files("cli").joinpath("context_template")


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
