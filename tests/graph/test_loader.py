"""Tests for the graphify graph.json loader."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.graph.loader import (
    GraphLoadError,
    _normalize_edge,
    _normalize_node,
    graph_path,
    graphify_available,
    load_graph,
)
from core.graph.store import GraphStore


def test_graph_path(tmp_path: Path) -> None:
    expected = tmp_path / ".fcc" / "graph" / "graph.json"
    assert graph_path(tmp_path) == expected


def test_graphify_available() -> None:
    result = graphify_available()
    assert isinstance(result, bool)


def test_load_missing_file(tmp_path: Path) -> None:
    with pytest.raises(GraphLoadError, match="not found"):
        load_graph(tmp_path)


def test_load_malformed_json(tmp_path: Path) -> None:
    graph_dir = tmp_path / ".fcc" / "graph"
    graph_dir.mkdir(parents=True)
    (graph_dir / "graph.json").write_text("not json", encoding="utf-8")
    with pytest.raises(GraphLoadError, match="Malformed JSON"):
        load_graph(tmp_path)


def test_load_top_level_not_dict(tmp_path: Path) -> None:
    graph_dir = tmp_path / ".fcc" / "graph"
    graph_dir.mkdir(parents=True)
    (graph_dir / "graph.json").write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(GraphLoadError, match="JSON object"):
        load_graph(tmp_path)


def test_load_minimal_graph(tmp_path: Path) -> None:
    graph_dir = tmp_path / ".fcc" / "graph"
    graph_dir.mkdir(parents=True)
    data = {"nodes": [], "edges": [], "communities": []}
    (graph_dir / "graph.json").write_text(json.dumps(data), encoding="utf-8")
    store = load_graph(tmp_path)
    assert store.entity_count() == 0
    assert store.relation_count() == 0


def test_load_complete_graph(tmp_path: Path) -> None:
    graph_dir = tmp_path / ".fcc" / "graph"
    graph_dir.mkdir(parents=True)
    data = {
        "nodes": [
            {
                "id": "src/auth.py::AuthManager",
                "name": "AuthManager",
                "type": "class",
                "file": "src/auth.py",
                "line": 42,
                "community": "auth-infra",
                "centrality": 0.87,
                "metadata": {
                    "docstring": "Central auth state",
                    "intents": ["HACK: mutates global state"],
                },
            },
            {
                "id": "src/api.py::ApiClient",
                "name": "ApiClient",
                "type": "class",
                "file": "src/api.py",
                "line": 15,
            },
        ],
        "edges": [
            {
                "source": "src/api.py::ApiClient",
                "target": "src/auth.py::AuthManager",
                "type": "CALLS",
                "confidence": "EXTRACTED",
            }
        ],
        "communities": [
            {
                "id": "auth-infra",
                "label": "Authentication & Identity",
                "size": 12,
                "central_nodes": ["AuthManager"],
            }
        ],
    }
    (graph_dir / "graph.json").write_text(json.dumps(data), encoding="utf-8")
    store = load_graph(tmp_path)
    assert store.entity_count() == 2
    assert store.relation_count() == 1
    assert store.community_count() == 1

    auth = store.get_entity("src/auth.py::AuthManager")
    assert auth is not None
    assert auth["name"] == "AuthManager"
    assert auth["centrality"] == 0.87
    assert auth["docstring"] == "Central auth state"
    assert auth["intents"] == ["HACK: mutates global state"]

    version = store.version()
    assert version is not None
    assert "T" in version


def test_load_invalid_node_id(tmp_path: Path) -> None:
    graph_dir = tmp_path / ".fcc" / "graph"
    graph_dir.mkdir(parents=True)
    data = {"nodes": [{"name": "NoID"}], "edges": []}
    (graph_dir / "graph.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(GraphLoadError, match="valid 'id'"):
        load_graph(tmp_path)


def test_load_invalid_edge_source(tmp_path: Path) -> None:
    graph_dir = tmp_path / ".fcc" / "graph"
    graph_dir.mkdir(parents=True)
    data = {
        "nodes": [{"id": "a", "name": "A"}],
        "edges": [{"target": "a"}],
    }
    (graph_dir / "graph.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(GraphLoadError, match="valid 'source'"):
        load_graph(tmp_path)


def test_load_small_file_ok(tmp_path: Path) -> None:
    """Small files should load without size-guard issues."""
    graph_dir = tmp_path / ".fcc" / "graph"
    graph_dir.mkdir(parents=True)
    (graph_dir / "graph.json").write_text(
        '{"nodes":[], "edges":[]}', encoding="utf-8"
    )
    store = load_graph(tmp_path)
    assert store.entity_count() == 0
