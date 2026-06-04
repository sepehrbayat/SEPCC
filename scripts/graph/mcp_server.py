"""FCC Graph MCP server — stdio JSON-RPC for knowledge graph tools.

Usage in .mcp.json:
  {"fcc-graph": {"command": "uvx", "args": ["--from", "fcc-graph-server", "fcc-graph-server"],
   "env": {"FCC_PROJECT_ROOT": "${CLAUDE_PROJECT_DIR:-.}"}}}
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


_cached_query: object | None = None
_cache_error: str | None = None  # "missing" or "corrupted"


def _get_query() -> object | None:
    """Load the graph once and cache for the life of the process (B2 fix).

    Returns a GraphQuery or None.  The string ``_cache_error`` is set to
    "missing" (no graph.json), "corrupted" (file exists but failed to load),
    or None (success).
    """
    global _cached_query, _cache_error
    if _cached_query is not None or _cache_error is not None:
        return _cached_query

    root = os.environ.get("FCC_PROJECT_ROOT", os.getcwd())
    graph_json = Path(root) / ".fcc" / "graph" / "graph.json"

    if not graph_json.is_file():
        _cache_error = "missing"
        return None

    try:
        from core.graph import load_graph
        from core.graph.query import GraphQuery
        store = load_graph(Path(root))
        _cached_query = GraphQuery(store)
        return _cached_query
    except Exception:
        _cache_error = "corrupted"
        return None


def _handle_request(request: dict) -> dict:
    method = request.get("method", "")
    params = request.get("params", {})
    req_id = request.get("id")
    try:
        if method == "tools/list":
            return _tools_list(req_id)
        elif method == "tools/call":
            return _tools_call(params, req_id)
        else:
            return _error(req_id, -32601, f"Unknown method: {method}")
    except Exception as exc:
        return _error(req_id, -32603, str(exc))


def _tools_list(req_id: object) -> dict:
    tools = [
        {"name": "fcc_graph_search", "description": "Search the knowledge graph for entities by name or description.",
         "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "top_n": {"type": "integer", "default": 10}}, "required": ["query"]}},
        {"name": "fcc_graph_neighbors", "description": "Get N-hop neighborhood of an entity — its dependencies and dependents.",
         "inputSchema": {"type": "object", "properties": {"entity_id": {"type": "string"}, "depth": {"type": "integer", "default": 1}, "direction": {"type": "string", "enum": ["in", "out", "both"], "default": "both"}}, "required": ["entity_id"]}},
        {"name": "fcc_graph_impact", "description": "Transitive closure analysis — what breaks if these entities change? Supports relation_type filtering and test-exclusion for production-only blast radius.",
         "inputSchema": {"type": "object", "properties": {"entity_ids": {"type": "array", "items": {"type": "string"}}, "relation_types": {"type": "array", "items": {"type": "string"}, "description": "Optional: filter by edge relation type (calls, references, imports, inherits, uses, etc.)"}, "exclude_tests": {"type": "boolean", "description": "Exclude test/smoke files from affected set for production-only risk"}}, "required": ["entity_ids"]}},
        {"name": "fcc_graph_path", "description": "Shortest dependency path between two entities. Use relation_types to filter by edge type and exclude_tests to avoid spurious paths through test files.",
         "inputSchema": {"type": "object", "properties": {"source": {"type": "string"}, "target": {"type": "string"}, "relation_types": {"type": "array", "items": {"type": "string"}, "description": "Optional: only follow these edge types (e.g. [\"imports\", \"imports_from\"])"}, "exclude_tests": {"type": "boolean", "description": "Skip test/smoke entities during traversal"}}, "required": ["source", "target"]}},
        {"name": "fcc_graph_god_nodes", "description": "Most-depended-on entities ranked by in-degree centrality. Set exclude_external=true to filter out Python builtins (str, int, Exception, etc.)",
         "inputSchema": {"type": "object", "properties": {"top_n": {"type": "integer", "default": 10}, "community": {"type": "string"}, "exclude_external": {"type": "boolean", "description": "Filter out Python builtins and external symbols"}}, "required": []}},
        {"name": "fcc_graph_community", "description": "Get the community an entity belongs to and all its peers.",
         "inputSchema": {"type": "object", "properties": {"entity_id": {"type": "string"}}, "required": ["entity_id"]}},
        {"name": "fcc_graph_entity", "description": "Get full details for a specific entity by ID.",
         "inputSchema": {"type": "object", "properties": {"entity_id": {"type": "string"}}, "required": ["entity_id"]}},
        {"name": "fcc_graph_explain", "description": "Plain-language explanation of an entity — what it is, what it depends on, what depends on it, and its community context. No LLM needed.",
         "inputSchema": {"type": "object", "properties": {"entity_id": {"type": "string"}}, "required": ["entity_id"]}},
        {"name": "fcc_graph_inspect", "description": "Rich entity inspection with docstrings, signatures, connections — understand what an entity does without opening the source file.",
         "inputSchema": {"type": "object", "properties": {"entity_id": {"type": "string"}}, "required": ["entity_id"]}},
        {"name": "fcc_graph_stats", "description": "Return graph summary statistics (entity/relation/community/counts, commit staleness, needs_update flag).",
         "inputSchema": {"type": "object", "properties": {}, "required": []}},
    ]
    return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools}}


def _tools_call(params: dict, req_id: object) -> dict:
    tool_name = params.get("name", "")
    arguments = params.get("arguments", {})

    known_tools = {
        "fcc_graph_search", "fcc_graph_neighbors", "fcc_graph_impact",
        "fcc_graph_path", "fcc_graph_god_nodes", "fcc_graph_community",
        "fcc_graph_entity", "fcc_graph_stats", "fcc_graph_explain",
        "fcc_graph_inspect",
    }
    if tool_name not in known_tools:
        return _error(req_id, -32601, f"Unknown tool: {tool_name}")

    # Validate required parameters per JSON-RPC 2.0 (-32602 = Invalid params)
    _REQUIRED_PARAMS = {
        "fcc_graph_search": ("query",),
        "fcc_graph_neighbors": ("entity_id",),
        "fcc_graph_impact": ("entity_ids",),
        "fcc_graph_path": ("source", "target"),
        "fcc_graph_god_nodes": (),
        "fcc_graph_community": ("entity_id",),
        "fcc_graph_entity": ("entity_id",),
        "fcc_graph_stats": (),
        "fcc_graph_explain": ("entity_id",),
        "fcc_graph_inspect": ("entity_id",),
    }
    for param in _REQUIRED_PARAMS.get(tool_name, ()):
        if param not in arguments:
            return _error(req_id, -32602, f"Missing required parameter: {param}")

    query = _get_query()
    if query is None:
        if _cache_error == "corrupted":
            msg = "Knowledge graph file exists but is corrupted or malformed. Rebuild with: fcc-bootstrap-context --install-graphify"
        else:
            msg = "No knowledge graph found. Run: fcc-bootstrap-context --install-graphify"
        return {"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": json.dumps({"error": "graph_unavailable", "message": msg})}]}}

    handler_map = {
        "fcc_graph_search": lambda: query.search(arguments["query"], arguments.get("top_n", 10)),
        "fcc_graph_neighbors": lambda: query.neighbors(arguments["entity_id"], arguments.get("depth", 1), arguments.get("direction", "both")),
        "fcc_graph_impact": lambda: query.impact(
            arguments["entity_ids"],
            arguments.get("relation_types"),
            arguments.get("exclude_tests", False),
        ),
        "fcc_graph_path": lambda: query.path(
            arguments["source"],
            arguments["target"],
            arguments.get("relation_types"),
            arguments.get("exclude_tests", False),
        ),
        "fcc_graph_god_nodes": lambda: query.god_nodes(
            arguments.get("top_n", 10),
            arguments.get("community"),
            arguments.get("exclude_external", False),
        ),
        "fcc_graph_community": lambda: query.community(arguments["entity_id"]),
        "fcc_graph_entity": lambda: query.entity(arguments["entity_id"]),
        "fcc_graph_stats": lambda: query.stats(),
        "fcc_graph_explain": lambda: query.explain(arguments["entity_id"]),
        "fcc_graph_inspect": lambda: query.inspect(arguments["entity_id"]),
    }
    result = handler_map[tool_name]()
    return {"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": json.dumps(result, default=str)}]}}


def _error(req_id: object, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            err = _error(None, -32700, "Parse error")
            sys.stdout.write(json.dumps(err) + "\n")
            sys.stdout.flush()
            continue
        response = _handle_request(request)
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
