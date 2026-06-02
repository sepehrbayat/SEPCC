"""Integration tests for graph context in hooks."""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOKS_DIR = REPO_ROOT / "scripts" / "hooks"


def _load_hook(name: str):
    import sys
    sys.path.insert(0, str(HOOKS_DIR))
    spec = importlib.util.spec_from_file_location(name, HOOKS_DIR / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_session_start_has_graph_function() -> None:
    m = _load_hook("session_start.py")
    assert hasattr(m, "_graph_context")


def test_session_start_no_graph_no_crash(tmp_path: Path) -> None:
    m = _load_hook("session_start.py")
    result = m._graph_context(tmp_path)
    assert result == ""


def test_user_prompt_has_graph_function() -> None:
    m = _load_hook("user_prompt_submit.py")
    assert hasattr(m, "_graph_task_context")


def test_user_prompt_no_graph_no_crash(tmp_path: Path) -> None:
    m = _load_hook("user_prompt_submit.py")
    result = m._graph_task_context("test prompt", tmp_path)
    assert result == ""


def test_precompact_has_anchors_function() -> None:
    m = _load_hook("precompact.py")
    assert hasattr(m, "_graph_anchors")


def test_precompact_no_graph_no_crash(tmp_path: Path) -> None:
    m = _load_hook("precompact.py")
    result = m._graph_anchors(tmp_path)
    assert result == ""
