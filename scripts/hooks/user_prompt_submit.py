"""Add tiny FCC context-routing hints for prompts that need orchestration."""

from __future__ import annotations

from _shared import emit_hook_json, prompt_routing_hint, read_hook_input, run_hook


def main() -> None:
    data = read_hook_input()
    prompt = str(data.get("prompt", ""))
    payload = prompt_routing_hint(prompt)
    emit_hook_json("UserPromptSubmit", additional_context=payload)


if __name__ == "__main__":
    run_hook("UserPromptSubmit", main)
