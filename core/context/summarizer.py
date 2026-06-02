"""Deterministic compact summarization helpers for FCC context files."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_DECISION_RE = re.compile(
    r"\b(decided|decision|choose|chosen|never)\b",
    re.IGNORECASE,
)


def compact_lines(text: str, *, max_lines: int = 12, max_chars: int = 1800) -> str:
    """Keep readable markdown lines without letting context payloads sprawl."""
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


def extract_section(text: str, heading: str) -> str:
    """Return markdown content under a second-level heading."""
    normalized = heading.strip().lower()
    capture = False
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            current = stripped[3:].strip().lower()
            if capture:
                break
            capture = current == normalized
            continue
        if capture:
            lines.append(line)
    return "\n".join(lines).strip()


def bulletize(lines: list[str], *, max_items: int = 5) -> list[str]:
    """Normalize free-form lines into short markdown bullets."""
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


def extract_decisions(text: str, *, max_items: int = 5) -> list[str]:
    """Extract decision-shaped lines from transcript or handoff text."""
    candidates = [
        line
        for line in re.split(r"[\r\n.]+", text)
        if _DECISION_RE.search(line) is not None
    ]
    return bulletize(candidates, max_items=max_items)


def parse_transcript_text(transcript_path: Path | str | None) -> str:
    """Extract compact user/assistant text from a Claude Code JSONL transcript."""
    if transcript_path is None:
        return ""
    path = Path(transcript_path)
    if not path.is_file():
        return ""

    entries: list[str] = []
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
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
    """Summarize transcript text deterministically without an LLM call."""
    if not text.strip():
        return ["- No transcript summary was available."]
    meaningful = [
        line
        for line in text.splitlines()
        if not line.lower().startswith("assistant: i'll inspect")
    ]
    return bulletize(meaningful[-max_items:], max_items=max_items)


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
