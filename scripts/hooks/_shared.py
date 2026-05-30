"""Shared stdlib helpers for FCC Claude Code project hooks."""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MAX_CONTEXT_CHARS = 3600
CONTEXT_DIR = Path(".fcc") / "context"
FACTS_FILE = CONTEXT_DIR / "facts.md"
DECISIONS_FILE = CONTEXT_DIR / "decisions.md"
HANDOFF_FILE = CONTEXT_DIR / "handoff.md"
RUNTIME_CONTRACT_FILE = CONTEXT_DIR / "agent-runtime.md"
PLUGIN_POLICY_FILE = Path(".fcc") / "plugin-policy.yml"

_DECISION_RE = re.compile(
    r"\b(decided|decision|choose|chosen|must|default|owner|do not|never)\b",
    re.IGNORECASE,
)


def read_hook_input() -> dict[str, Any]:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        return {}
    if isinstance(data, dict):
        return data
    return {}


def project_root(data: dict[str, Any]) -> Path:
    raw = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
    return Path(str(raw)).expanduser().resolve()


def emit_hook_json(
    event_name: str,
    *,
    additional_context: str = "",
    system_message: str = "",
) -> None:
    output: dict[str, Any] = {"suppressOutput": True}
    if additional_context:
        output["hookSpecificOutput"] = {
            "hookEventName": event_name,
            "additionalContext": additional_context[:MAX_CONTEXT_CHARS],
        }
    if system_message:
        output["systemMessage"] = system_message[:240]
    print(json.dumps(output, ensure_ascii=True, separators=(",", ":")))


def run_hook(event_name: str, callback: Callable[[], None]) -> None:
    """Run a hook callback and always emit Claude Code hook JSON."""
    try:
        callback()
    except Exception as exc:
        emit_hook_json(
            event_name,
            system_message=f"FCC {event_name} hook failed: {type(exc).__name__}",
        )


def read_text(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def compact_lines(text: str, *, max_lines: int = 14, max_chars: int = 1800) -> str:
    out: list[str] = []
    used = 0
    in_fence = False
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not line.strip():
            continue
        next_len = len(line) + 1
        if used + next_len > max_chars:
            break
        out.append(line)
        used += next_len
        if len(out) >= max_lines:
            break
    return "\n".join(out)


def runtime_contract(root: Path, *, max_chars: int = 1500) -> str:
    """Return the compact FCC runtime contract for injection."""
    contract = read_text(root / RUNTIME_CONTRACT_FILE)
    if not contract:
        contract = _fallback_runtime_contract()
    return compact_lines(contract, max_lines=22, max_chars=max_chars)


def prompt_routing_hint(prompt: str) -> str:
    """Return a tiny routing hint for prompts that need FCC orchestration."""
    lowered = prompt.lower()
    hints: list[str] = []
    if any(term in lowered for term in _RECALL_TERMS):
        hints.append(
            "recall: use handoff first, MemSearch for memory, Token Savior for code"
        )
    if any(term in lowered for term in _REVIEW_TERMS):
        hints.append(
            "review: use fcc-code-reviewer/product-logic subagents when useful"
        )
    if any(term in lowered for term in _RESEARCH_TERMS):
        hints.append("research: use fcc-researcher and cite primary sources")
    if any(term in lowered for term in _LARGE_WORK_TERMS):
        hints.append("large task: use bounded multi-agent review; verify before final")
    if any(term in lowered for term in _LOOP_TERMS):
        hints.append(
            "loop: Ralph Loop only if configured, bounded, and test-verifiable"
        )
    if not hints:
        return ""
    return "FCC routing hint: " + "; ".join(hints[:3]) + "."


def _fallback_runtime_contract() -> str:
    return "\n".join(
        [
            "# FCC Agent Runtime",
            "- FCC is the provider/router; do not add another routing proxy.",
            "- Trust SessionStart context, then .fcc/context/handoff.md.",
            "- Durable local facts belong in CLAUDE.local.md.",
            "- Memory owner: MemSearch. Code retrieval owner: Token Savior.",
            "- Store raw logs in SQLite sidecar; do not replay transcripts.",
            "- Use subagents for large research/review/logic audits.",
            "- Ralph Loop is optional and only for bounded verified loops.",
        ]
    )


def extract_section(text: str, heading: str) -> str:
    wanted = heading.strip().lower()
    capture = False
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            current = stripped[3:].strip().lower()
            if capture:
                break
            capture = current == wanted
            continue
        if capture:
            lines.append(line)
    return "\n".join(lines).strip()


_RECALL_TERMS = (
    "recall",
    "remember",
    "forgot",
    "memory",
    "handoff",
    "context",
    "decision",
    "resume",
    "continue",
)
_REVIEW_TERMS = (
    "review",
    "audit",
    "line by line",
    "bug",
    "risk",
    "regression",
    "logic",
)
_RESEARCH_TERMS = (
    "research",
    "docs",
    "documentation",
    "tweets",
    "twitter",
    "x.com",
    "best practice",
    "latest",
)
_LARGE_WORK_TERMS = (
    "multi-file",
    "architecture",
    "long-running",
    "end to end",
    "thorough",
    "verify",
    "tests",
)
_LOOP_TERMS = ("ralph", "loop", "iterate", "until passing", "autonomous")


def parse_transcript_text(transcript_path: Path | str | None) -> str:
    if transcript_path is None:
        return ""
    path = Path(transcript_path)
    if not path.is_file():
        return ""

    entries: list[str] = []
    for raw_line in read_text(path).splitlines():
        try:
            obj = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        role = _extract_role(obj)
        if role not in {"user", "assistant"}:
            continue
        text = _extract_text(obj)
        if text:
            entries.append(f"{role}: {text}")
    return "\n".join(entries[-10:])


def summarize_transcript(text: str, *, max_items: int = 5) -> list[str]:
    if not text.strip():
        return ["- No transcript summary was available."]
    return bulletize(text.splitlines()[-max_items:], max_items=max_items)


def extract_decisions(text: str, *, max_items: int = 5) -> list[str]:
    candidates = [
        line
        for line in re.split(r"[\r\n.]+", text)
        if _DECISION_RE.search(line) is not None
    ]
    return bulletize(candidates, max_items=max_items)


def bulletize(lines: list[str], *, max_items: int = 5) -> list[str]:
    bullets: list[str] = []
    seen: set[str] = set()
    for raw_line in lines:
        line = re.sub(r"\s+", " ", raw_line).strip(" -\t")
        if not line:
            continue
        if len(line) > 180:
            line = f"{line[:177].rstrip()}..."
        key = line.lower()
        if key in seen:
            continue
        seen.add(key)
        bullets.append(f"- {line}")
        if len(bullets) >= max_items:
            break
    return bullets


def regenerate_handoff(root: Path, transcript_path: Path | str | None) -> None:
    context_dir = root / CONTEXT_DIR
    context_dir.mkdir(parents=True, exist_ok=True)
    handoff_path = root / HANDOFF_FILE
    facts_path = root / FACTS_FILE
    decisions_path = root / DECISIONS_FILE

    transcript_text = parse_transcript_text(transcript_path)
    existing_handoff = read_text(handoff_path)
    facts_text = read_text(facts_path)
    decisions_text = read_text(decisions_path)
    must_lines = compact_lines(
        "\n".join(
            part
            for part in (
                extract_section(existing_handoff, "Must Not Forget"),
                facts_text,
            )
            if part.strip()
        ),
        max_lines=8,
        max_chars=1200,
    )
    if not must_lines:
        must_lines = "- Add project-critical facts to CLAUDE.local.md."

    current_state = "\n".join(summarize_transcript(transcript_text, max_items=5))
    decision_lines = extract_decisions(
        "\n".join(part for part in (transcript_text, decisions_text) if part.strip()),
        max_items=5,
    )
    decisions = "\n".join(decision_lines) or "- No new decisions detected."
    handoff_path.write_text(
        "\n".join(
            [
                "# FCC Handoff",
                "",
                "## Must Not Forget",
                must_lines,
                "",
                "## Current State",
                current_state,
                "",
                "## Decisions",
                decisions,
                "",
                "## Next Steps",
                "- Run /verify-context before major edits.",
                "- Store raw logs in the SQLite sidecar; do not replay them into chat.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    if decision_lines:
        append_new_decisions(decisions_path, decision_lines)


def append_new_decisions(path: Path, decisions: list[str]) -> None:
    existing = read_text(path)
    existing_keys = {line.strip().lower() for line in existing.splitlines()}
    new_items = [
        item for item in decisions if item.strip().lower() not in existing_keys
    ]
    if not new_items:
        return
    stamp = datetime.now(UTC).date().isoformat()
    prefix = "" if existing.endswith("\n") or not existing else "\n"
    block = "\n".join([f"{prefix}## {stamp}", *new_items, ""])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(block)


def _extract_role(obj: dict[str, Any]) -> str | None:
    role = obj.get("role")
    if isinstance(role, str):
        return role
    message = obj.get("message")
    if isinstance(message, dict):
        nested_role = message.get("role")
        if isinstance(nested_role, str):
            return nested_role
    entry_type = obj.get("type")
    if entry_type in {"user", "assistant"}:
        return str(entry_type)
    return None


def _extract_text(obj: Any) -> str:
    if isinstance(obj, str):
        return obj
    if isinstance(obj, list):
        return " ".join(_extract_text(item) for item in obj).strip()
    if not isinstance(obj, dict):
        return ""
    block_type = obj.get("type")
    if block_type not in {None, "text", "message", "user", "assistant"}:
        return ""
    parts: list[str] = []
    for key in ("text", "content"):
        value = obj.get(key)
        if value is not None:
            text = _extract_text(value)
            if text:
                parts.append(text)
    message = obj.get("message")
    if message is not None:
        text = _extract_text(message)
        if text:
            parts.append(text)
    return " ".join(parts).strip()
