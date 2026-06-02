"""FCC Knowledge Graph — Graphify-powered codebase structural understanding."""

from core.graph.context import (
    build_handoff_context,
    build_session_bootstrap,
    build_structural_anchors,
    build_task_injection,
)
from core.graph.loader import GraphLoadError, graph_path, graphify_available, load_graph
from core.graph.query import GraphQuery
from core.graph.store import GraphStore

__all__ = [
    "GraphLoadError",
    "GraphQuery",
    "GraphStore",
    "build_handoff_context",
    "build_session_bootstrap",
    "build_structural_anchors",
    "build_task_injection",
    "graph_path",
    "graphify_available",
    "load_graph",
]
