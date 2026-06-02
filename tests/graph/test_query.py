"""Unit tests for GraphQuery traversal operations."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from core.graph.query import GraphQuery
from core.graph.store import GraphStore


@pytest.fixture
def query() -> GraphQuery:
    store = GraphStore(Path(tempfile.mkdtemp()))
    store.insert_entity({
        "id": "a.py::A", "name": "A", "type": "class",
        "file": "a.py", "line": 1, "community": "core", "centrality": 0.9,
    })
    store.insert_entity({
        "id": "b.py::B", "name": "B", "type": "class",
        "file": "b.py", "line": 1, "community": "core", "centrality": 0.5,
    })
    store.insert_entity({
        "id": "c.py::C", "name": "C", "type": "class",
        "file": "c.py", "line": 1, "community": "ui", "centrality": 0.3,
    })
    store.insert_entity({
        "id": "d.py::D", "name": "D", "type": "function",
        "file": "d.py", "line": 10,
    })
    store.insert_relation({"source": "a.py::A", "target": "b.py::B", "type": "CALLS", "confidence": "EXTRACTED"})
    store.insert_relation({"source": "a.py::A", "target": "c.py::C", "type": "CALLS", "confidence": "EXTRACTED"})
    store.insert_relation({"source": "b.py::B", "target": "d.py::D", "type": "CALLS", "confidence": "EXTRACTED"})
    store.commit()
    return GraphQuery(store)


def test_entity_found(query: GraphQuery) -> None:
    assert query.entity("a.py::A") is not None
    assert query.entity("a.py::A")["name"] == "A"


def test_entity_not_found(query: GraphQuery) -> None:
    assert query.entity("nonexistent") is None


def test_neighbors_outgoing(query: GraphQuery) -> None:
    r = query.neighbors("a.py::A", direction="out")
    assert {d["id"] for d in r["dependencies"]} == {"b.py::B", "c.py::C"}


def test_neighbors_incoming(query: GraphQuery) -> None:
    r = query.neighbors("b.py::B", direction="in")
    assert {d["id"] for d in r["dependents"]} == {"a.py::A"}


def test_neighbors_depth_2(query: GraphQuery) -> None:
    r = query.neighbors("a.py::A", depth=2, direction="out")
    assert "d.py::D" in {d["id"] for d in r["dependencies"]}


def test_neighbors_not_found(query: GraphQuery) -> None:
    r = query.neighbors("nonexistent")
    assert r["entity"] is None
    assert r["dependencies"] == []


def test_community_peers_in_neighbors(query: GraphQuery) -> None:
    r = query.neighbors("a.py::A")
    peers = {p["id"] for p in r["community_peers"]}
    assert "b.py::B" in peers
    assert "c.py::C" not in peers


def test_impact_returns_risk(query: GraphQuery) -> None:
    r = query.impact(["a.py::A"])
    assert r["estimated_risk"] in ("low", "medium", "high")
    assert r["files_touched"] >= 1


def test_impact_empty(query: GraphQuery) -> None:
    r = query.impact(["nonexistent"])
    assert r["files_touched"] == 0


def test_path_direct(query: GraphQuery) -> None:
    steps = query.path("a.py::A", "b.py::B")
    assert len(steps) == 1
    assert steps[0]["next"] == "b.py::B"


def test_path_indirect(query: GraphQuery) -> None:
    steps = query.path("a.py::A", "d.py::D")
    assert len(steps) >= 1
    assert steps[-1]["next"] == "d.py::D"


def test_path_disconnected(query: GraphQuery) -> None:
    assert query.path("d.py::D", "a.py::A") == []


def test_path_same_node(query: GraphQuery) -> None:
    assert query.path("a.py::A", "a.py::A") == []


def test_god_nodes(query: GraphQuery) -> None:
    gods = query.god_nodes(top_n=10)
    assert len(gods) >= 1
    assert gods[0]["name"] == "A"


def test_god_nodes_scoped(query: GraphQuery) -> None:
    gods = query.god_nodes(top_n=10, community="ui")
    assert len(gods) == 1
    assert gods[0]["name"] == "C"


def test_search(query: GraphQuery) -> None:
    results = query.search("A", top_n=10)
    assert len(results) >= 1
    assert results[0]["name"] == "A"


def test_search_no_match(query: GraphQuery) -> None:
    assert query.search("zzz_nonexistent") == []


def test_community(query: GraphQuery) -> None:
    r = query.community("a.py::A")
    assert r is not None
    assert r["size"] >= 1


def test_community_no_membership(query: GraphQuery) -> None:
    r = query.community("d.py::D")
    assert r is not None
    assert r["community"] is None


def test_community_not_found(query: GraphQuery) -> None:
    assert query.community("nonexistent") is None


def test_stats(query: GraphQuery) -> None:
    s = query.stats()
    assert s["entity_count"] == 4
    assert s["relation_count"] == 3
    assert s["community_count"] >= 0
