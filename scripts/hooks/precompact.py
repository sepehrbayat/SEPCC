"""Carry forward only must-not-forget handoff facts before compaction."""

from __future__ import annotations

import contextlib
import re

from _shared import (
    HANDOFF_FILE,
    compact_lines,
    emit_hook_json,
    extract_section,
    project_root,
    read_hook_input,
    read_text,
    regenerate_handoff,
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


def _adaptive_graph_context(root: object, transcript_text: str) -> str:
    """Build adaptive graph context from the conversation transcript.

    Extracts code-relevant terms from the transcript, searches the graph
    for matching entities, and returns focused context about those entities
    rather than generic top-5 communities.

    Falls back to structural anchors when no relevant entities are found
    or when the transcript is empty.
    """
    if not transcript_text or not transcript_text.strip():
        return _graph_anchors(root)

    try:
        from core.graph import load_graph
        from core.graph.context import build_task_injection, build_session_bootstrap
        from core.graph.query import GraphQuery
    except ImportError:
        return ""
    from pathlib import Path

    if not isinstance(root, Path):
        return ""
    graph_json = root / ".fcc" / "graph" / "graph.json"
    if not graph_json.is_file():
        return ""

    try:
        store = load_graph(root)
        query = GraphQuery(store)
    except Exception:
        return ""

    # Extract candidate terms: identifiers, file paths, class names from
    # the transcript. Prioritize CamelCase and snake_case terms.
    id_pattern = re.compile(r'\b([A-Z][a-z]+(?:[A-Z][a-z]+)+|[a-z]+(?:_[a-z]+){2,})\b')
    identifiers = id_pattern.findall(transcript_text)

    # Also extract file references like "path/to/file.py"
    file_pattern = re.compile(r'[\w/-]+\.(?:py|yml|yaml|toml|json|md|js|ps1|sh)')
    file_refs = file_pattern.findall(transcript_text)

    # Deduplicate and prioritize
    candidate_terms: list[str] = []
    seen: set[str] = set()
    for term in identifiers + file_refs:
        lower = term.lower()
        if lower not in seen and len(lower) > 3:
            seen.add(lower)
            candidate_terms.append(term)

    if not candidate_terms:
        return _graph_anchors(root)

    # Search graph for each candidate term
    matched_entities: list[dict] = []
    matched_ids: set[str] = set()
    for term in candidate_terms[:15]:
        for result in query.search(term, top_n=2):
            if result["id"] not in matched_ids:
                matched_ids.add(result["id"])
                matched_entities.append(result)

    if not matched_entities:
        return _graph_anchors(root)

    # Build focused context
    lines = ["## Conversation-Relevant Graph Context"]
    code_entities = [e for e in matched_entities if e.get("type") == "code"]

    if code_entities:
        lines.append(f"From the conversation, {len(code_entities)} relevant entities:")
        for e in code_entities[:8]:
            file = e.get("file", "?")
            line = e.get("line")
            loc = f"{file}:{line}" if line else file
            conns = query._store.connection_count(e["id"])
            cent = float(e.get("centrality", 0) or 0)
            god = " *(god node)*" if cent > 0.6 else ""
            comm = f" [community {e['community']}]" if e.get("community") else ""
            lines.append(f"  - `{e['name']}` ({loc}) — {conns} connections{god}{comm}")

        # Also include top communities these entities belong to
        comms = {e.get("community") for e in code_entities if e.get("community")}
        if comms:
            comm_labels = []
            for cid in list(comms)[:5]:
                c = query._store.get_community(cid)
                label = c.get("label", cid) if c else cid
                comm_labels.append(f"{cid} ({label})")
            lines.append(f"\nRelevant communities: {', '.join(comm_labels)}")

            # Include top gods from each relevant community
            gods: list[str] = []
            seen_gods: set[str] = set()
            for cid in list(comms)[:3]:
                for g in query.god_nodes(top_n=3, community=cid, exclude_external=True):
                    if g["name"] not in seen_gods:
                        seen_gods.add(g["name"])
                        gods.append(f"{g['name']} (cent {g['centrality']:.2f})")
            if gods:
                lines.append(f"Key entities in these communities: {', '.join(gods[:6])}")
    else:
        # No code entities — use generic anchors
        return _graph_anchors(root)

    return "\n".join(lines)


def main() -> None:
    data = read_hook_input()
    root = project_root(data)

    # Regenerate handoff before reading — ensures PreCompact captures
    # the latest state even when Stop hasn't fired yet.
    with contextlib.suppress(Exception):
        regenerate_handoff(root, None)

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

    # Build adaptive graph context from conversation transcript
    transcript_text = _extract_transcript_text(data)
    anchors = _adaptive_graph_context(root, transcript_text)

    payload = ""
    if must:
        payload = "FCC must-not-forget facts before compaction:\n" + must
        if continuity:
            payload += "\n\nFCC active continuity:\n" + continuity
        if anchors:
            payload += "\n\n" + anchors
    emit_hook_json("PreCompact", additional_context=payload)


def _extract_transcript_text(data: dict) -> str:
    """Extract transcript/conversation text from the hook input data.

    Claude Code PreCompact hook sends transcript history fields.
    Tries multiple possible field names.
    """
    # Look for transcript text in common field names
    for key in ("transcript", "conversation", "messages", "history"):
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            return val
        if isinstance(val, list):
            parts: list[str] = []
            for item in val[-20:]:  # Last 20 messages
                if isinstance(item, dict):
                    text = item.get("content") or item.get("text") or ""
                    if isinstance(text, str):
                        parts.append(text)
                elif isinstance(item, str):
                    parts.append(item)
            if parts:
                return "\n".join(parts)
    # Fallback: look for any string value that looks like conversation
    for val in data.values():
        if isinstance(val, str) and len(val) > 100:
            return val
    return ""


if __name__ == "__main__":
    run_hook("PreCompact", main)
