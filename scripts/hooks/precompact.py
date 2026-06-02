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


def _graph_anchors(root: object) -> str:
    """Build structural anchors from the knowledge graph."""
    try:
        from core.graph import load_graph
        from core.graph.context import build_structural_anchors
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
        return build_structural_anchors(query)
    except Exception as exc:
        return f"## Structural Anchors\n- Graph unavailable ({type(exc).__name__})."


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
    anchors = _graph_anchors(root)
    payload = ""
    if must:
        payload = "FCC must-not-forget facts before compaction:\n" + must
        if continuity:
            payload += "\n\nFCC active continuity:\n" + continuity
        if anchors:
            payload += "\n\n" + anchors
    emit_hook_json("PreCompact", additional_context=payload)


if __name__ == "__main__":
    run_hook("PreCompact", main)
