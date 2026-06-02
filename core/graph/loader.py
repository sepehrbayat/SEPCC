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
    edges = data.get("edges")
    communities = data.get("communities")

    if not isinstance(nodes, list):
        raise GraphLoadError("graph.json 'nodes' must be a list")
    if not isinstance(edges, list):
        raise GraphLoadError("graph.json 'edges' must be a list")

    store = GraphStore(root)
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

    store.commit()

    # Track version: use mtime as version string
    mtime = path.stat().st_mtime
    from datetime import UTC, datetime
    version = datetime.fromtimestamp(mtime, UTC).isoformat()
    store.set_version(version)

    return store


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
    metadata = node.get("metadata")
    if isinstance(metadata, dict):
        docstring = metadata.get("docstring", "")
        intents = metadata.get("intents", [])
    else:
        docstring = ""
        intents = []
    return {
        "id": node["id"],
        "name": node.get("name", node["id"]),
        "type": node.get("type", "unknown"),
        "file": node.get("file"),
        "line": node.get("line"),
        "community": node.get("community"),
        "centrality": node.get("centrality"),
        "docstring": docstring,
        "intents": intents if isinstance(intents, list) else [],
    }


def _normalize_edge(edge: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": edge["source"],
        "target": edge["target"],
        "type": edge.get("type", "UNKNOWN"),
        "confidence": edge.get("confidence", "INFERRED"),
    }
