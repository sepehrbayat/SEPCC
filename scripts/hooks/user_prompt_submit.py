"""Add tiny FCC context-routing hints for prompts that need orchestration."""

from __future__ import annotations

import os
import sys

from _shared import (
    emit_hook_json,
    name_active_session,
    project_root,
    prompt_enhancement_outputs,
    prompt_routing_hint,
    read_hook_input,
    run_hook,
    session_name_from_prompt,
)


def _debugger_pipeline_context(prompt: str, root: object) -> str:
    """Build the debugger pipeline injection, if a transition is detected.

    Returns an empty string when the debugger module is unavailable
    (e.g., running outside the SEPCC package environment).
    """
    try:
        from core.debugger.trigger import debugger_pipeline_context as _build
    except ImportError:
        return ""
    from pathlib import Path

    if not isinstance(root, Path):
        return ""
    return _build(prompt, root)


def main() -> None:
    data = read_hook_input()
    prompt = str(data.get("prompt", ""))
    root = project_root(data)
    name = session_name_from_prompt(prompt)
    name_active_session(root, name)
    enhancement_context, enhancement_message = prompt_enhancement_outputs(prompt, root)
    pipeline_context = _debugger_pipeline_context(prompt, root)
    payload = " ".join(
        part
        for part in (
            enhancement_context,
            prompt_routing_hint(prompt),
            pipeline_context,
        )
        if part
    )
    emit_hook_json(
        "UserPromptSubmit",
        additional_context=payload,
        system_message=enhancement_message,
    )


if __name__ == "__main__":
    run_hook("UserPromptSubmit", main)
