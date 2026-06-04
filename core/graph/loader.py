"""Load graphify's graph.json into a GraphStore."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from core.graph.store import GraphStore


class GraphLoadError(Exception):
    """Raised when graph.json cannot be loaded or is malformed."""


def graph_path(root: Path) -> Path:
    """Return the path to graphify's graph.json."""
    return root / ".fcc" / "graph" / "graph.json"


def graphify_available() -> bool:
    """Check if the `graphify` CLI is on PATH."""
    return shutil.which("graphify") is not None


def load_graph(root: Path) -> GraphStore:
    """Load graphify's graph.json into a fresh GraphStore.

    Raises GraphLoadError on missing, malformed, or invalid data.
    """
    path = graph_path(root)
    if not path.is_file():
        raise GraphLoadError(f"Graph file not found: {path}")

    # Size guard: warn on large files
    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb > 50:
        raise GraphLoadError(
            f"graph.json is {size_mb:.0f}MB (max 50MB). "
            "Consider excluding generated/template directories."
        )

    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GraphLoadError(f"Malformed JSON in graph.json: {exc}") from exc

    if not isinstance(data, dict):
        raise GraphLoadError("graph.json top-level must be a JSON object")

    nodes = data.get("nodes")
    # graphify ≥ 0.8 uses "links"; older versions used "edges".
    # Prefer "edges" when "links" is absent/null, to handle hybrid files.
    links_val = data.get("links")
    edges = links_val if isinstance(links_val, list) else data.get("edges")
    communities = data.get("communities")

    if not isinstance(nodes, list):
        raise GraphLoadError("graph.json 'nodes' must be a list")
    if not isinstance(edges, list):
        raise GraphLoadError(
            "graph.json must contain 'links' (graphify ≥ 0.8) or 'edges' (legacy) as a list"
        )

    store = GraphStore(root)
    try:
        store.clear()

        for node in nodes:
            if not isinstance(node, dict):
                raise GraphLoadError(f"graph.json 'nodes' element must be a dict, got: {type(node).__name__}")
            _validate_node(node)
            entity = _normalize_node(node)
            store.insert_entity(entity)

        for edge in edges:
            if not isinstance(edge, dict):
                raise GraphLoadError(f"graph.json 'edges' element must be a dict, got: {type(edge).__name__}")
            _validate_edge(edge)
            rel = _normalize_edge(edge)
            store.insert_relation(rel)

        if isinstance(communities, list):
            for comm in communities:
                if not isinstance(comm, dict):
                    raise GraphLoadError(f"graph.json 'communities' element must be a dict, got: {type(comm).__name__}")
                _validate_community(comm)
                store.insert_community(comm)
        elif not communities:
            # Auto-derive communities from node data when no top-level list exists
            # (graphify cluster-only embeds community IDs on nodes, not as top-level)
            _derive_communities_from_nodes(nodes, store)

        store.commit()

        # Compute centrality from graph topology when graphify didn't assign it
        _compute_centrality(nodes, store)

        # Track version: use mtime as version string
        mtime = path.stat().st_mtime
        from datetime import UTC, datetime
        version = datetime.fromtimestamp(mtime, UTC).isoformat()
        store.set_version(version)

        # Store commit hash if graphify embedded it
        built_at = data.get("built_at_commit")
        if isinstance(built_at, str) and built_at.strip():
            store.meta_set("built_at_commit", built_at.strip())

        # Store graph topology stats for benchmark reporting
        store.meta_set("source_node_count", str(len(nodes)))
        store.meta_set("source_edge_count", str(len(edges)))

        # Save entity snapshot for diff-based change detection
        _save_entity_snapshot(nodes, edges, store)

        return store
    except Exception:
        store.close()
        raise


def _validate_node(node: dict[str, Any]) -> None:
    if not isinstance(node.get("id"), str) or not node["id"].strip():
        raise GraphLoadError(f"Node missing valid 'id': {node}")


def _validate_edge(edge: dict[str, Any]) -> None:
    if not isinstance(edge.get("source"), str) or not edge["source"].strip():
        raise GraphLoadError(f"Edge missing valid 'source': {edge}")
    if not isinstance(edge.get("target"), str) or not edge["target"].strip():
        raise GraphLoadError(f"Edge missing valid 'target': {edge}")


def _validate_community(comm: dict[str, Any]) -> None:
    if not isinstance(comm.get("id"), str) or not comm["id"].strip():
        raise GraphLoadError(f"Community missing valid 'id': {comm}")


def _normalize_node(node: dict[str, Any]) -> dict[str, Any]:
    # graphify ≥ 0.8 renamed fields: name→label, type→file_type, file→source_file,
    # line→source_location; docstring/intents moved out of metadata into top-level
    metadata = node.get("metadata")
    if isinstance(metadata, dict):
        docstring = metadata.get("docstring", "") or node.get("docstring", "")
        intents = metadata.get("intents")
        if intents is None:
            intents = node.get("intents", [])
    else:
        docstring = node.get("docstring", "")
        intents = node.get("intents", [])
    return {
        "id": node["id"],
        "name": node.get("label") or node.get("name", node["id"]),
        "type": node.get("file_type") or node.get("type", "unknown"),
        "file": node.get("source_file") or node.get("file"),
        "line": node.get("source_location") or node.get("line"),
        "community": node.get("community"),
        "centrality": node.get("centrality"),
        "docstring": docstring,
        "intents": intents if isinstance(intents, list) else [],
    }


def _normalize_edge(edge: dict[str, Any]) -> dict[str, Any]:
    # graphify ≥ 0.8 renamed 'type' → 'relation'
    return {
        "source": edge["source"],
        "target": edge["target"],
        "type": edge.get("relation") or edge.get("type", "UNKNOWN"),
        "confidence": edge.get("confidence", "INFERRED"),
    }


def _derive_communities_from_nodes(
    nodes: list[dict[str, Any]], store: GraphStore
) -> None:
    """Auto-derive community metadata from node-level ``community`` fields.

    Used when graphify embeds community IDs on each node but provides no
    top-level ``communities`` list (e.g. ``cluster-only`` output).
    """
    from collections import Counter

    comm_counts: Counter[str] = Counter()
    for node in nodes:
        if isinstance(node, dict) and node.get("community") is not None:
            comm_counts[str(node["community"])] += 1

    for comm_id, size in comm_counts.items():
        store.insert_community({
            "id": comm_id,
            "label": f"Community {comm_id}",
            "size": size,
            "central_nodes": [],
        })


def _save_entity_snapshot(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]], store: GraphStore
) -> None:
    """Save a compact entity snapshot to schema_meta for diff-based change detection.

    Stores a JSON mapping of ``entity_id → {name, type, file}`` plus edge
    relation counts so subsequent ``diff()`` calls can detect added, removed,
    and modified entities.
    """
    import json as _json
    snapshot = {
        str(n["id"]): {"name": n.get("label") or n.get("name", n["id"]),
                       "type": n.get("file_type") or n.get("type", "unknown"),
                       "file": n.get("source_file") or n.get("file")}
        for n in nodes if isinstance(n, dict) and n.get("id")
    }
    store.meta_set("entity_snapshot", _json.dumps(snapshot, separators=(",", ":")))
    store.meta_set("entity_snapshot_count", str(len(snapshot)))
    store.meta_set("edge_snapshot_count", str(len(edges)))


def _compute_centrality(
    nodes: list[dict[str, Any]], store: GraphStore
) -> None:
    """Compute directional degree centrality from the raw graph topology.

    graphify AST-only extraction does not assign centrality.  This computes:

    - **in_degree** — how many relations point TO this entity (its dependents).
      This is the architecturally meaningful "god node" metric: high in-degree
      means many things depend on you, so changing you has wide blast radius.
    - **out_degree** — how many relations point FROM this entity (its deps).
    - **centrality** — normalised 0–1 based on *in-degree* (dependents), which
      correctly identifies entities that are depended upon by many others.

    All three are stored in the entities table.
    """
    from collections import Counter

    in_deg: Counter[str] = Counter()
    out_deg: Counter[str] = Counter()
    all_rels = store._conn.execute(
        "SELECT source_id, target_id FROM relations"
    ).fetchall()
    for row in all_rels:
        out_deg[str(row["source_id"])] += 1
        in_deg[str(row["target_id"])] += 1

    # Ensure every node appears in the counters (Counter.__missing__ returns 0
    # but never creates the key, so we must explicitly assign).
    for node in nodes:
        if isinstance(node, dict) and node.get("id"):
            eid = str(node["id"])
            in_deg[eid] = in_deg.get(eid, 0)
            out_deg[eid] = out_deg.get(eid, 0)
    max_in = max(in_deg.values()) if in_deg else 0
    if max_in == 0:
        max_in = 1  # All-zero graph → every node gets 0.0
    for eid in in_deg:
        score = round(in_deg[eid] / max_in, 4)
        store._conn.execute(
            "UPDATE entities SET centrality = ?, in_degree = ?, out_degree = ? WHERE id = ?",
            (score, in_deg.get(eid, 0), out_deg.get(eid, 0), eid),
        )
    store.commit()
