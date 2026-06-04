"""Build graph-aware context injection strings for FCC hooks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.graph.loader import graph_path, load_graph
from core.graph.query import GraphQuery


def _get_query(root: Path | object) -> GraphQuery | None:
    from pathlib import Path as _Path
    if not isinstance(root, _Path):
        return None
    path = graph_path(root)
    if not path.is_file():
        return None
    try:
        store = load_graph(root)
        return GraphQuery(store)
    except Exception:
        return None


def build_session_bootstrap(
    graph: GraphQuery,
    task_hint: str | None = None,
    changed_files: list[str] | None = None,
    token_budget: int = 600,
) -> str:
    lines: list[str] = ["## Project Structure"]
    communities = graph._store.get_communities()
    if communities:
        lines.append("Primary domains:")
        for c in communities[:5]:
            label = c.get("label", c["id"])
            size = c.get("size", 0)
            lines.append(f"  • {c['id']} ({size} nodes) — {label}")

    gods = graph.god_nodes(top_n=8)
    if gods:
        lines.append("\nKey abstractions:")
        for g in gods:
            conns = g.get("connection_count", 0)
            cent = g.get("centrality", 0)
            lines.append(f"  • {g['name']} (god, {cent:.2f} centrality, {conns} connections)")

    if changed_files:
        lines.append(f"\nActive changes: {len(changed_files)} files modified")
    result = "\n".join(lines)
    if len(result) > token_budget:
        result = result[:token_budget - 3] + "..."
    return result


def build_task_injection(
    graph: GraphQuery,
    user_message: str,
    token_budget: int = 250,
) -> str:
    if not user_message.strip():
        return ""
    words = [w.lower() for w in user_message.split() if len(w) > 2]
    if not words:
        return ""
    seen_ids: set[str] = set()
    matches: list[dict[str, Any]] = []
    for word in words[:5]:
        for r in graph.search(word, top_n=3):
            if r["id"] not in seen_ids:
                seen_ids.add(r["id"])
                matches.append(r)
    if not matches:
        return ""
    lines: list[str] = ["", "[Graph Context]", "Matched entities:"]
    for m in matches[:5]:
        file = m.get("file", "?")
        line = m.get("line")
        loc = f"{file}:{line}" if line else file
        conns = graph._store.connection_count(m["id"])
        god = " — god node" if (m.get("centrality") or 0) > 0.7 else ""
        community = m.get("community", "")
        lines.append(f"  • {m['name']} ({loc}){god}, {conns} connections")
        if community:
            lines.append(f"    Community: {community}")
        # Include docstring if available (from semantic enrichment)
        doc = m.get("docstring")
        if doc and isinstance(doc, str) and doc.strip():
            # Truncate long docstrings to first sentence
            brief = doc.split(".")[0].strip()[:120]
            if brief:
                lines.append(f"    {brief}.")
    result = "\n".join(lines)
    if len(result) > token_budget:
        result = result[:token_budget - 3] + "..."
    return result


def build_structural_anchors(graph: GraphQuery) -> str:
    communities = graph._store.get_communities()
    gods = graph.god_nodes(top_n=5)
    version = graph._store.version() or "unknown"
    lines = ["## Structural Anchors"]
    if communities:
        top = communities[:3]
        comm_str = ", ".join(f"{c['id']} ({c.get('size', 0)})" for c in top)
        lines.append(f"- Primary communities: {comm_str}")
    if gods:
        god_names = ", ".join(g["name"] for g in gods[:5])
        lines.append(f"- God nodes: {god_names}")
    lines.append(f"- Graph version: {version}")
    return "\n".join(lines)


def build_handoff_context(graph: GraphQuery) -> str:
    communities = graph._store.get_communities()
    gods = graph.god_nodes(top_n=5)
    version = graph._store.version() or "unknown"
    lines = [
        "## Structural Context",
        f"- Primary communities: {', '.join(c['id'] for c in communities[:5])}",
    ]
    if gods:
        lines.append(f"- God nodes: {', '.join(g['name'] for g in gods[:5])}")
    lines.append(f"- Graph version: {version}")
    return "\n".join(lines)
