"""Tests for graph health checks in context doctor."""

from __future__ import annotations

from pathlib import Path


def test_graph_missing_warning(tmp_path: Path) -> None:
    from cli.context_doctor import _check_graph_health

    issues = _check_graph_health(tmp_path)
    assert len(issues) == 1
    assert "No knowledge graph" in issues[0]


def test_graph_healthy(tmp_path: Path) -> None:
    graph_dir = tmp_path / ".fcc" / "graph"
    graph_dir.mkdir(parents=True)
    (graph_dir / "graph.json").write_text("{}", encoding="utf-8")

    from cli.context_doctor import _check_graph_health

    issues = _check_graph_health(tmp_path)
    assert len(issues) == 0
