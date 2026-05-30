"""Regenerate FCC current-state handoff after a Claude Code turn."""

from __future__ import annotations

from pathlib import Path

from _shared import (
    emit_hook_json,
    project_root,
    read_hook_input,
    regenerate_handoff,
    run_hook,
)


def main() -> None:
    data = read_hook_input()
    root = project_root(data)
    transcript = data.get("transcript_path")
    transcript_path = Path(str(transcript)) if transcript else None
    regenerate_handoff(root, transcript_path)
    emit_hook_json("Stop", system_message="FCC handoff updated")


if __name__ == "__main__":
    run_hook("Stop", main)
