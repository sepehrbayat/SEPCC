"""Inject compact project context at Claude Code session start."""

from __future__ import annotations

from _shared import (
    compact_lines,
    emit_hook_json,
    project_root,
    read_hook_input,
    read_text,
    run_hook,
    runtime_contract,
)


def main() -> None:
    data = read_hook_input()
    root = project_root(data)
    sections: list[str] = [
        f"## .fcc/context/agent-runtime.md\n{runtime_contract(root)}"
    ]
    for rel_path in (
        "CLAUDE.md",
        "CLAUDE.local.md",
        ".fcc/context/handoff.md",
    ):
        content = compact_lines(read_text(root / rel_path), max_lines=12, max_chars=900)
        if content:
            sections.append(f"## {rel_path}\n{content}")

    payload = "FCC project context:\n" + "\n\n".join(sections)
    emit_hook_json("SessionStart", additional_context=payload)


if __name__ == "__main__":
    run_hook("SessionStart", main)
