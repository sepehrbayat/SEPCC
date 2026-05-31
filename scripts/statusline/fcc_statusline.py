"""Compact Claude Code status line for FCC-bootstrapped projects."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

MAX_STATUS_CHARS = 120


def main() -> None:
    data = _read_input()
    model = _nested_str(data, ("model", "display_name")) or "Claude"
    current_dir = _nested_str(data, ("workspace", "current_dir")) or ""
    project = Path(current_dir).name if current_dir else "workspace"
    used = _nested_number(data, ("context_window", "used_percentage"))

    parts = ["FCC", model, project]
    if used is not None:
        parts.append(f"ctx {used:.0f}%")

    line = " | ".join(part for part in parts if part)
    print(line[:MAX_STATUS_CHARS])


def _read_input() -> dict[str, Any]:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        return {}
    if isinstance(data, dict):
        return data
    return {}


def _nested_str(data: dict[str, Any], path: tuple[str, ...]) -> str:
    value: Any = data
    for key in path:
        if not isinstance(value, dict):
            return ""
        value = value.get(key)
    return value if isinstance(value, str) else ""


def _nested_number(data: dict[str, Any], path: tuple[str, ...]) -> float | None:
    value: Any = data
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    if isinstance(value, int | float):
        return float(value)
    return None


if __name__ == "__main__":
    main()
