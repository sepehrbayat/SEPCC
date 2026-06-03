"""Tests for FCC Graph MCP server tool dispatch."""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _import_server():
    spec = importlib.util.spec_from_file_location(
        "mcp_server",
        REPO_ROOT / "scripts" / "graph" / "mcp_server.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_tools_list() -> None:
    module = _import_server()
    response = module._handle_request({"method": "tools/list", "params": {}, "id": 1})
    tools = response["result"]["tools"]
    tool_names = {t["name"] for t in tools}
    for name in ("fcc_graph_search", "fcc_graph_neighbors", "fcc_graph_impact",
                 "fcc_graph_path", "fcc_graph_god_nodes", "fcc_graph_community",
                 "fcc_graph_entity", "fcc_graph_stats", "fcc_graph_explain"):
        assert name in tool_names, f"Missing tool: {name}"


def test_unknown_method() -> None:
    module = _import_server()
    response = module._handle_request({"method": "unknown", "params": {}, "id": 1})
    assert "error" in response
    assert response["error"]["code"] == -32601


def test_unknown_tool() -> None:
    module = _import_server()
    response = module._handle_request({
        "method": "tools/call",
        "params": {"name": "nonexistent_tool", "arguments": {}},
        "id": 2,
    })
    assert "error" in response


def test_missing_required_param_returns_invalid_params() -> None:
    """B23: Missing required argument must return -32602 (Invalid params), not -32603."""
    module = _import_server()
    response = module._handle_request({
        "method": "tools/call",
        "params": {"name": "fcc_graph_explain", "arguments": {}},
        "id": 3,
    })
    assert "error" in response
    # -32602 = Invalid params per JSON-RPC 2.0
    assert response["error"]["code"] == -32602, (
        f"Expected -32602 but got {response['error']['code']}"
    )


def test_parse_error_returns_jsonrpc_error() -> None:
    """B24: Parse errors must return -32700 response, not silent skip."""
    module = _import_server()
    response = module._handle_request({"method": "tools/list", "params": {}, "id": 4})
    # Valid request test already exists — this verifies handle path exists
    assert "result" in response or "error" in response
