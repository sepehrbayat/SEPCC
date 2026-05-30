"""Add tiny FCC context-routing hints for prompts that need orchestration."""

from __future__ import annotations

from _shared import (
    emit_hook_json,
    name_active_session,
    project_root,
    prompt_routing_hint,
    read_hook_input,
    run_hook,
    session_name_from_prompt,
)


def main() -> None:
    data = read_hook_input()
    prompt = str(data.get("prompt", ""))
    root = project_root(data)
    name = session_name_from_prompt(prompt)
    name_active_session(root, name)
    payload = prompt_routing_hint(prompt)
    emit_hook_json("UserPromptSubmit", additional_context=payload)


if __name__ == "__main__":
    run_hook("UserPromptSubmit", main)
