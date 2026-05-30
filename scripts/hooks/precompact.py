"""Carry forward only must-not-forget handoff facts before compaction."""

from __future__ import annotations

from _shared import (
    HANDOFF_FILE,
    compact_lines,
    emit_hook_json,
    extract_section,
    project_root,
    read_hook_input,
    read_text,
    run_hook,
)


def main() -> None:
    data = read_hook_input()
    root = project_root(data)
    handoff = read_text(root / HANDOFF_FILE)
    must = compact_lines(
        extract_section(handoff, "Must Not Forget"),
        max_lines=8,
        max_chars=1200,
    )
    continuity = compact_lines(
        "\n".join(
            part
            for part in (
                extract_section(handoff, "Current State"),
                extract_section(handoff, "Next Steps"),
            )
            if part.strip()
        ),
        max_lines=4,
        max_chars=700,
    )
    payload = ""
    if must:
        payload = "FCC must-not-forget facts before compaction:\n" + must
        if continuity:
            payload += "\n\nFCC active continuity:\n" + continuity
    emit_hook_json("PreCompact", additional_context=payload)


if __name__ == "__main__":
    run_hook("PreCompact", main)
