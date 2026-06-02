"""Unit tests for graph context injection builders."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from core.graph.context import (
    _get_query,
    build_handoff_context,
    build_session_bootstrap,
    build_structural_anchors,
    build_task_injection,
)
from core.graph.query import GraphQuery
from core.graph.store import GraphStore


@pytest.fixture
def query() -> GraphQuery:
    store = GraphStore(Path(tempfile.mkdtemp()))
    store.insert_entity({
        "id": "src/auth.py::AuthManager", "name": "AuthManager", "type": "class",
        "file": "src/auth.py", "line": 42, "community": "auth-infra", "centrality": 0.92,
        "docstring": "Central auth state machine",
    })
    store.insert_entity({
        "id": "src/auth.py::ErrorFormatter", "name": "ErrorFormatter", "type": "class",
        "file": "src/auth.py", "line": 89, "community": "auth-infra", "centrality": 0.45,
    })
    store.insert_entity({
        "id": "src/api.py::ApiGateway", "name": "ApiGateway", "type": "class",
        "file": "src/api.py", "line": 10, "community": "api-gateway", "centrality": 0.87,
    })
    store.insert_relation({"source": "src/api.py::ApiGateway", "target": "src/auth.py::AuthManager", "type": "CALLS", "confidence": "EXTRACTED"})
    store.insert_relation({"source": "src/auth.py::AuthManager", "target": "src/auth.py::ErrorFormatter", "type": "CALLS", "confidence": "EXTRACTED"})
    store.insert_community({"id": "auth-infra", "label": "Authentication & Identity", "size": 12, "central_nodes": ["AuthManager"]})
    store.insert_community({"id": "api-gateway", "label": "API Gateway", "size": 8, "central_nodes": ["ApiGateway"]})
    store.set_version("abc123")
    store.commit()
    return GraphQuery(store)


def test_session_bootstrap_has_communities(query: GraphQuery) -> None:
    result = build_session_bootstrap(query)
    assert "auth-infra" in result
    assert "api-gateway" in result


def test_session_bootstrap_has_god_nodes(query: GraphQuery) -> None:
    result = build_session_bootstrap(query)
    assert "AuthManager" in result
    assert "ApiGateway" in result


def test_session_bootstrap_within_budget(query: GraphQuery) -> None:
    result = build_session_bootstrap(query, token_budget=100)
    assert len(result) <= 103


def test_task_injection_matches_entities(query: GraphQuery) -> None:
    result = build_task_injection(query, "fix the auth manager bug")
    assert "AuthManager" in result
    assert "src/auth.py" in result


def test_task_injection_empty_no_match(query: GraphQuery) -> None:
    result = build_task_injection(query, "zzz nothing matches this")
    assert "AuthManager" not in result


def test_task_injection_empty_prompt(query: GraphQuery) -> None:
    result = build_task_injection(query, "")
    assert result == ""


def test_task_injection_within_budget(query: GraphQuery) -> None:
    result = build_task_injection(query, "auth", token_budget=100)
    assert len(result) <= 103


def test_structural_anchors_format(query: GraphQuery) -> None:
    result = build_structural_anchors(query)
    assert "Structural Anchors" in result
    assert "auth-infra" in result
    assert "abc123" in result


def test_handoff_context_format(query: GraphQuery) -> None:
    result = build_handoff_context(query)
    assert "Structural Context" in result
    assert "auth-infra" in result
    assert "abc123" in result


def test_get_query_no_graph(tmp_path: Path) -> None:
    result = _get_query(tmp_path)
    assert result is None
