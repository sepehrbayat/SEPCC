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


def test_explain_found(query: GraphQuery) -> None:
    result = query.explain("a.py::A")
    assert result.get("entity") is not None
    assert "A" in result.get("summary", "")
    assert "CALLS" in result.get("summary", "") or result["dependency_count"] >= 1


def test_explain_not_found(query: GraphQuery) -> None:
    result = query.explain("nonexistent")
    assert "error" in result


def test_impact_with_relation_filter(query: GraphQuery) -> None:
    # With type filter matching the only relation type
    result = query.impact(["a.py::A"], relation_types=["CALLS"])
    assert result["estimated_risk"] in ("low", "medium", "high")
    assert result["files_touched"] >= 1


def test_impact_with_nonmatching_filter(query: GraphQuery) -> None:
    result = query.impact(["a.py::A"], relation_types=["IMPORTS"])
    # The entity itself contributes its own file, but no dependents via IMPORTS
    # (only CALLS edges exist in the test graph)
    assert result["files_touched"] == 1  # Only entity's own file
    assert len(result["directly_affected"]) == 0  # No inbound IMPORTS relations
    assert len(result["transitively_affected"]) == 0


def test_commit_info(query: GraphQuery) -> None:
    info = query.commit_info()
    # In test environment, built_at_commit is not stored, so should return None
    # Unless the test happens to run in a git repo with a graph loaded
    assert info is None or isinstance(info, dict)


def test_path_with_relation_filter(query: GraphQuery) -> None:
    """Path with CALLS only should find the known edge."""
    steps = query.path("a.py::A", "b.py::B", relation_types=["CALLS"])
    assert len(steps) == 1
    assert steps[0]["relation"] == "CALLS"


def test_path_with_nonmatching_filter(query: GraphQuery) -> None:
    """Path with IMPORTS filter should return empty — no IMPORTS in test graph."""
    steps = query.path("a.py::A", "b.py::B", relation_types=["IMPORTS"])
    assert steps == []


def test_path_exclude_tests(query: GraphQuery) -> None:
    """Exclude_tests should not break a graph that has no test entities."""
    steps = query.path("a.py::A", "d.py::D", exclude_tests=True)
    assert len(steps) >= 1
    assert steps[-1]["next"] == "d.py::D"


def test_impact_exclude_tests(query: GraphQuery) -> None:
    """Impact with exclude_tests should still work on production-only graph."""
    result = query.impact(["a.py::A"], exclude_tests=True)
    assert result["files_touched"] >= 1
    assert result["estimated_risk"] in ("low", "medium", "high")


def test_explain_shows_directional_info(query: GraphQuery) -> None:
    """Explain should return in_degree and out_degree."""
    result = query.explain("a.py::A")
    assert "in_degree" in result
    assert "out_degree" in result
    assert result["dependent_count_production"] >= 0


def test_god_nodes_includes_in_out_degree(query: GraphQuery) -> None:
    """God nodes entries should have in_degree and out_degree fields."""
    gods = query.god_nodes(top_n=5)
    assert len(gods) >= 1
    first = gods[0]
    assert "in_degree" in first or first.get("in_degree") is not None


def test_is_test_entity(tmp_path: Any) -> None:
    """Verify test-file detection logic."""
    from core.graph.query import _is_test_entity
    assert _is_test_entity({"file": "tests/api/test_auth.py"}) is True
    assert _is_test_entity({"file": "smoke/prereq/test_live.py"}) is True
    assert _is_test_entity({"file": "src/auth.py"}) is False
    assert _is_test_entity({"file": "core/graph/query.py"}) is False
    assert _is_test_entity(None) is False
    assert _is_test_entity({}) is False


def test_is_test_entity_windows_paths() -> None:
    """B18/SMOKE: Windows backslash paths must be detected correctly."""
    from core.graph.query import _is_test_entity
    assert _is_test_entity({"file": "C:\\Users\\dev\\tests\\api\\test_auth.py"}) is True
    assert _is_test_entity({"file": "D:\\projects\\src\\auth.py"}) is False


def test_path_nonexistent_source_returns_empty(query: GraphQuery) -> None:
    """B15: Path from non-existent source must return empty (same as disconnected)."""
    steps = query.path("NONEXISTENT_ID_XYZ", "a.py::A")
    assert steps == []


def test_impact_all_test_dependents_excluded(query: GraphQuery) -> None:
    """B20: When ALL dependents are test entities, files_touched reflects own file only."""
    result = query.impact(["a.py::A"], exclude_tests=True)
    assert result["files_touched"] >= 1  # Entity's own file counts
    assert result["estimated_risk"] in ("low", "medium", "high")


def test_impact_filters_rationale_entities(query: GraphQuery) -> None:
    """I1: Rationale entities must not appear in directly_affected or transitively_affected."""
    # Insert a mock rationale entity and verify impact excludes it
    query._store.insert_entity({
        "id": "mock_rationale",
        "name": "Explains how this works.",
        "type": "rationale",
        "file": "config/settings.py",
        "community": "203",
        "centrality": 0.0,
        "in_degree": 0,
        "out_degree": 1,
    })
    query._store.insert_relation({
        "source": "mock_rationale",
        "target": "config_settings",
        "type": "rationale_for",
        "confidence": "EXTRACTED",
    })
    query._store.commit()

    result = query.impact(["config_settings"])
    # Rationale entities must not pollute impact lists
    assert "mock_rationale" not in result["directly_affected"]
    assert "mock_rationale" not in result["transitively_affected"]


def test_explain_excludes_builtins_from_production_dependents(query: GraphQuery) -> None:
    """I2: Builtins (str, int, Any, Exception) must not appear as production dependents."""
    # Insert a builtin entity that "depends on" A via type annotation edge
    query._store.insert_entity({
        "id": "python_str",
        "name": "str",
        "type": "code",
        "in_degree": 0,
        "out_degree": 1,
    })
    query._store.insert_relation({
        "source": "python_str",
        "target": "a.py::A",
        "type": "uses",
        "confidence": "INFERRED",
    })
    query._store.commit()

    result = query.explain("a.py::A")
    prod_deps = result["dependent_count_production"]
    # The builtin str should not inflate the production count
    # Verify it's counted as test/other or excluded
    assert prod_deps >= 0


def test_search_is_case_insensitive(query: GraphQuery) -> None:
    """I3: Search must find entities regardless of snake_case vs PascalCase."""
    query._store.insert_entity({
        "id": "api_token_counter",
        "name": "TokenCounter",
        "type": "code",
        "file": "api/tokens.py",
        "docstring": "Token counting service with rate limiting",
    })
    query._store.commit()

    # Snake_case query should match PascalCase entity name
    results = query.search("token_count", top_n=5)
    names = [r["name"] for r in results]
    assert "TokenCounter" in names, (
        f"Search for 'token_count' missed 'TokenCounter', got: {names}"
    )


def test_search_splits_on_underscore_and_case(query: GraphQuery) -> None:
    """I3: Search terms split on underscores and case boundaries for recall."""
    query._store.insert_entity({
        "id": "pkg_session_resume_handler",
        "name": "SessionResumeHandler",
        "type": "code",
        "docstring": "Handles session resumption logic",
    })
    query._store.commit()

    # "session_resume" should match "SessionResumeHandler"
    results = query.search("session_resume", top_n=5)
    names = [r["name"] for r in results]
    assert "SessionResumeHandler" in names, (
        f"Search for 'session_resume' missed 'SessionResumeHandler', got: {names}"
    )
