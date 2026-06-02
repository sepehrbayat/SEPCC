"""End-to-end tests for the Graphify knowledge graph integration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.graph.loader import load_graph
from core.graph.query import GraphQuery


@pytest.mark.live
def test_full_graph_lifecycle(tmp_path: Path) -> None:
    """Build a mock graph.json, load it, and query it end-to-end."""
    graph_dir = tmp_path / ".fcc" / "graph"
    graph_dir.mkdir(parents=True)

    data = {
        "nodes": [
            {"id": "src/main.py::main", "name": "main", "type": "function",
             "file": "src/main.py", "line": 1, "community": "core", "centrality": 1.0},
            {"id": "src/lib.py::helper", "name": "helper", "type": "function",
             "file": "src/lib.py", "line": 5, "community": "core", "centrality": 0.5},
            {"id": "src/ui.py::render", "name": "render", "type": "function",
             "file": "src/ui.py", "line": 20, "community": "ui", "centrality": 0.3},
        ],
        "edges": [
            {"source": "src/main.py::main", "target": "src/lib.py::helper",
             "type": "CALLS", "confidence": "EXTRACTED"},
            {"source": "src/main.py::main", "target": "src/ui.py::render",
             "type": "CALLS", "confidence": "EXTRACTED"},
        ],
        "communities": [
            {"id": "core", "label": "Core Logic", "size": 2, "central_nodes": ["main"]},
            {"id": "ui", "label": "User Interface", "size": 1, "central_nodes": ["render"]},
        ],
    }
    (graph_dir / "graph.json").write_text(json.dumps(data), encoding="utf-8")

    store = load_graph(tmp_path)
    assert store.entity_count() == 3
    assert store.relation_count() == 2
    assert store.community_count() == 2
    assert store.version() is not None

    query = GraphQuery(store)

    assert query.entity("src/main.py::main")["name"] == "main"

    deps = {d["name"] for d in query.neighbors("src/main.py::main", direction="out")["dependencies"]}
    assert deps == {"helper", "render"}

    impact = query.impact(["src/main.py::main"])
    assert impact["files_touched"] >= 1

    steps = query.path("src/main.py::main", "src/lib.py::helper")
    assert steps[0]["next"] == "src/lib.py::helper"

    gods = query.god_nodes(top_n=10)
    assert gods[0]["name"] == "main"

    assert query.search("helper")[0]["name"] == "helper"
    assert query.community("src/main.py::main") is not None
    assert query.stats()["entity_count"] == 3


def test_context_injection_full_pipeline(tmp_path: Path) -> None:
    """Verify all four context injection functions work with a real graph."""
    graph_dir = tmp_path / ".fcc" / "graph"
    graph_dir.mkdir(parents=True)

    data = {
        "nodes": [{"id": "src/auth.py::AuthManager", "name": "AuthManager",
                    "type": "class", "file": "src/auth.py", "line": 42,
                    "community": "auth-infra", "centrality": 0.92,
                    "metadata": {"docstring": "Central auth state"}}],
        "edges": [],
        "communities": [{"id": "auth-infra", "label": "Auth", "size": 1,
                         "central_nodes": ["AuthManager"]}],
    }
    (graph_dir / "graph.json").write_text(json.dumps(data), encoding="utf-8")

    store = load_graph(tmp_path)
    query = GraphQuery(store)

    from core.graph.context import (
        build_handoff_context,
        build_session_bootstrap,
        build_structural_anchors,
        build_task_injection,
    )

    bootstrap = build_session_bootstrap(query)
    assert "auth-infra" in bootstrap
    assert "AuthManager" in bootstrap

    task = build_task_injection(query, "fix the auth manager")
    assert "AuthManager" in task

    anchors = build_structural_anchors(query)
    assert "auth-infra" in anchors

    handoff = build_handoff_context(query)
    assert "auth-infra" in handoff


def test_graph_store_survives_close_and_reopen(tmp_path: Path) -> None:
    """Verify data persists across close() and reload."""
    graph_dir = tmp_path / ".fcc" / "graph"
    graph_dir.mkdir(parents=True)

    data = {"nodes": [{"id": "x", "name": "X", "type": "class"}], "edges": []}
    (graph_dir / "graph.json").write_text(json.dumps(data), encoding="utf-8")

    store1 = load_graph(tmp_path)
    assert store1.entity_count() == 1
    store1.close()

    store2 = load_graph(tmp_path)
    assert store2.entity_count() == 1
    assert store2.get_entity("x") is not None
    store2.close()
