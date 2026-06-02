"""Unit tests for GraphStore — SQLite schema and basic CRUD."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.graph.store import GraphStore


@pytest.fixture
def store(tmp_path: Path) -> GraphStore:
    return GraphStore(tmp_path)


def test_create_tables(store: GraphStore) -> None:
    tables = store._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    names = {row["name"] for row in tables}
    for required in ("entities", "relations", "communities"):
        assert required in names, f"Missing table: {required}"


def test_insert_entity(store: GraphStore) -> None:
    store.insert_entity({
        "id": "src/auth.py::AuthManager",
        "name": "AuthManager",
        "type": "class",
        "file": "src/auth.py",
        "line": 42,
        "community": "auth-infra",
        "centrality": 0.87,
        "docstring": "Central auth state",
        "intents": ["HACK: mutates global state"],
    })
    store.commit()
    entity = store.get_entity("src/auth.py::AuthManager")
    assert entity is not None
    assert entity["name"] == "AuthManager"
    assert entity["type"] == "class"
    assert entity["line"] == 42
    assert entity["centrality"] == 0.87
    assert entity["intents"] == ["HACK: mutates global state"]


def test_insert_entity_minimal(store: GraphStore) -> None:
    store.insert_entity({"id": "x.py::foo", "name": "foo", "type": "function"})
    store.commit()
    entity = store.get_entity("x.py::foo")
    assert entity is not None
    assert entity["name"] == "foo"
    assert entity["file"] is None
    assert entity["centrality"] is None


def test_insert_relation(store: GraphStore) -> None:
    store.insert_entity({"id": "a.py::A", "name": "A", "type": "class"})
    store.insert_entity({"id": "b.py::B", "name": "B", "type": "class"})
    store.insert_relation({
        "source": "a.py::A",
        "target": "b.py::B",
        "type": "CALLS",
        "confidence": "EXTRACTED",
    })
    store.commit()
    outgoing = store.get_outgoing_relations("a.py::A")
    assert len(outgoing) == 1
    assert outgoing[0]["target_id"] == "b.py::B"
    assert outgoing[0]["type"] == "CALLS"
    incoming = store.get_incoming_relations("b.py::B")
    assert len(incoming) == 1
    assert incoming[0]["source_id"] == "a.py::A"


def test_insert_community(store: GraphStore) -> None:
    store.insert_community({
        "id": "auth-infra",
        "label": "Authentication & Identity",
        "size": 12,
        "central_nodes": ["AuthManager", "TokenStore"],
    })
    store.commit()
    communities = store.get_communities()
    assert len(communities) == 1
    assert communities[0]["label"] == "Authentication & Identity"
    assert communities[0]["size"] == 12
    assert communities[0]["central_nodes"] == ["AuthManager", "TokenStore"]


def test_entity_count(store: GraphStore) -> None:
    assert store.entity_count() == 0
    store.insert_entity({"id": "a", "name": "A", "type": "class"})
    store.insert_entity({"id": "b", "name": "B", "type": "class"})
    store.commit()
    assert store.entity_count() == 2


def test_upsert_on_duplicate(store: GraphStore) -> None:
    store.insert_entity({"id": "x.py::X", "name": "OldName", "type": "class"})
    store.commit()
    store.insert_entity({"id": "x.py::X", "name": "NewName", "type": "function"})
    store.commit()
    entity = store.get_entity("x.py::X")
    assert entity is not None
    assert entity["name"] == "NewName"
    assert entity["type"] == "function"
    assert store.entity_count() == 1


def test_clear(store: GraphStore) -> None:
    store.insert_entity({"id": "a", "name": "A", "type": "class"})
    store.insert_relation({"source": "a", "target": "a", "type": "SELF", "confidence": "EXTRACTED"})
    store.insert_community({"id": "c", "label": "C", "size": 1, "central_nodes": []})
    store.commit()
    assert store.entity_count() == 1
    assert store.relation_count() == 1
    assert store.community_count() == 1
    store.clear()
    assert store.entity_count() == 0
    assert store.relation_count() == 0
    assert store.community_count() == 0


def test_fts_search(store: GraphStore) -> None:
    store.insert_entity({
        "id": "m.py::foo",
        "name": "process_request",
        "type": "function",
        "docstring": "Handles incoming HTTP requests with auth",
    })
    store.insert_entity({
        "id": "n.py::bar",
        "name": "calculate_total",
        "type": "function",
        "docstring": "Sums order line items",
    })
    store.commit()
    # "process" appears in a name so the LIKE fallback path also works
    results = store.search_fts("process", limit=10)
    assert len(results) >= 1
    names = [r["name"] for r in results]
    assert "process_request" in names


def test_fts_search_no_results(store: GraphStore) -> None:
    store.insert_entity({"id": "a", "name": "foo", "type": "class"})
    store.commit()
    results = store.search_fts("zzz_nonexistent_zzz", limit=10)
    assert results == []


def test_fts_search_docstring_only(store: GraphStore) -> None:
    """FTS5 must find text that only appears in docstring, not in name."""
    store.insert_entity({
        "id": "p.py::handler",
        "name": "handler",
        "type": "function",
        "docstring": "Implements OAuth2 token exchange",
    })
    store.commit()
    # "OAuth2" only appears in docstring — verifies FTS5 triggers work
    results = store.search_fts("OAuth2", limit=10)
    assert len(results) >= 1
    assert results[0]["name"] == "handler"


def test_double_close_no_error(store: GraphStore) -> None:
    """Double close() must not raise an error."""
    store.close()
    store.close()  # Should be a silent no-op


def test_top_by_centrality(store: GraphStore) -> None:
    store.insert_entity({"id": "a", "name": "low", "type": "class", "centrality": 0.1})
    store.insert_entity({"id": "b", "name": "mid", "type": "class", "centrality": 0.5})
    store.insert_entity({"id": "c", "name": "high", "type": "class", "centrality": 0.99})
    store.insert_entity({"id": "d", "name": "none", "type": "class"})
    store.commit()
    top = store.get_top_by_centrality(limit=10)
    assert len(top) == 3
    assert top[0]["name"] == "high"
    assert top[1]["name"] == "mid"
    assert top[2]["name"] == "low"


def test_top_by_centrality_scoped(store: GraphStore) -> None:
    store.insert_entity({"id": "a", "name": "A", "type": "class", "community": "x", "centrality": 0.9})
    store.insert_entity({"id": "b", "name": "B", "type": "class", "community": "y", "centrality": 0.5})
    store.commit()
    top = store.get_top_by_centrality(limit=10, community="x")
    assert len(top) == 1
    assert top[0]["name"] == "A"


def test_get_entities_by_community(store: GraphStore) -> None:
    store.insert_entity({"id": "a", "name": "A", "type": "class", "community": "infra"})
    store.insert_entity({"id": "b", "name": "B", "type": "class", "community": "infra"})
    store.insert_entity({"id": "c", "name": "C", "type": "class", "community": "ui"})
    store.commit()
    infra = store.get_entities_by_community("infra")
    assert len(infra) == 2
    names = {e["name"] for e in infra}
    assert names == {"A", "B"}


def test_connection_count(store: GraphStore) -> None:
    store.insert_entity({"id": "a", "name": "A", "type": "class"})
    store.insert_entity({"id": "b", "name": "B", "type": "class"})
    store.insert_entity({"id": "c", "name": "C", "type": "class"})
    store.insert_relation({"source": "a", "target": "b", "type": "CALLS", "confidence": "EXTRACTED"})
    store.insert_relation({"source": "c", "target": "a", "type": "IMPORTS", "confidence": "EXTRACTED"})
    store.commit()
    assert store.connection_count("a") == 2
    assert store.connection_count("b") == 1


def test_version_tracking(store: GraphStore) -> None:
    assert store.version() is None
    store.set_version("abc123def")
    assert store.version() == "abc123def"
    store.set_version("new456")
    assert store.version() == "new456"
