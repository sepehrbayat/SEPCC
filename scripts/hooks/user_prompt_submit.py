"""Add tiny FCC context-routing hints for prompts that need orchestration."""

from __future__ import annotations

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
    """Build the debugger pipeline injection, if a transition is detected."""
    try:
        from core.debugger.trigger import debugger_pipeline_context as _build
    except ImportError:
        return ""
    from pathlib import Path

    if not isinstance(root, Path):
        return ""
    return _build(prompt, root)


def _graph_task_context(prompt: str, root: object) -> str:
    """Build graph entity-match injection for this prompt."""
    try:
        from core.graph import load_graph
        from core.graph.context import build_task_injection
        from core.graph.query import GraphQuery
    except ImportError:
        return ""
    from pathlib import Path

    if not isinstance(root, Path):
        return ""
    graph_json = root / ".fcc" / "graph" / "graph.json"
    if not graph_json.is_file():
        return ""  # No graph installed — normal, not an error
    try:
        store = load_graph(root)
        query = GraphQuery(store)
        return build_task_injection(query, prompt)
    except Exception as exc:
        return f"[Graph Context] Graph unavailable ({type(exc).__name__})."


def main() -> None:
    data = read_hook_input()
    prompt = str(data.get("prompt", ""))
    root = project_root(data)
    name = session_name_from_prompt(prompt)
    name_active_session(root, name)
    enhancement_context, enhancement_message = prompt_enhancement_outputs(prompt, root)
    pipeline_context = _debugger_pipeline_context(prompt, root)
    graph_context = _graph_task_context(prompt, root)
    payload = " ".join(
        part
        for part in (
            enhancement_context,
            prompt_routing_hint(prompt, root),
            pipeline_context,
            graph_context,
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
