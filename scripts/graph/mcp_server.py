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


def _get_query() -> object | None:
    root = os.environ.get("FCC_PROJECT_ROOT", os.getcwd())
    try:
        from core.graph import load_graph
        from core.graph.query import GraphQuery
        store = load_graph(Path(root))
        return GraphQuery(store)
    except Exception:
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
        {"name": "fcc_graph_impact", "description": "Transitive closure analysis — what breaks if these entities change?",
         "inputSchema": {"type": "object", "properties": {"entity_ids": {"type": "array", "items": {"type": "string"}}}, "required": ["entity_ids"]}},
        {"name": "fcc_graph_path", "description": "Shortest dependency path between two entities.",
         "inputSchema": {"type": "object", "properties": {"source": {"type": "string"}, "target": {"type": "string"}}, "required": ["source", "target"]}},
        {"name": "fcc_graph_god_nodes", "description": "Most-connected/important entities in the codebase.",
         "inputSchema": {"type": "object", "properties": {"top_n": {"type": "integer", "default": 10}, "community": {"type": "string"}}, "required": []}},
        {"name": "fcc_graph_community", "description": "Get the community an entity belongs to and all its peers.",
         "inputSchema": {"type": "object", "properties": {"entity_id": {"type": "string"}}, "required": ["entity_id"]}},
        {"name": "fcc_graph_entity", "description": "Get full details for a specific entity by ID.",
         "inputSchema": {"type": "object", "properties": {"entity_id": {"type": "string"}}, "required": ["entity_id"]}},
        {"name": "fcc_graph_stats", "description": "Return graph summary statistics (entity/relation/community counts).",
         "inputSchema": {"type": "object", "properties": {}, "required": []}},
    ]
    return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools}}


def _tools_call(params: dict, req_id: object) -> dict:
    tool_name = params.get("name", "")
    arguments = params.get("arguments", {})

    known_tools = {
        "fcc_graph_search", "fcc_graph_neighbors", "fcc_graph_impact",
        "fcc_graph_path", "fcc_graph_god_nodes", "fcc_graph_community",
        "fcc_graph_entity", "fcc_graph_stats",
    }
    if tool_name not in known_tools:
        return _error(req_id, -32601, f"Unknown tool: {tool_name}")

    query = _get_query()
    if query is None:
        return {"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": json.dumps({"error": "graph_unavailable", "message": "No knowledge graph found. Run: fcc-bootstrap-context --install-graphify"})}]}}

    handler_map = {
        "fcc_graph_search": lambda: query.search(arguments["query"], arguments.get("top_n", 10)),
        "fcc_graph_neighbors": lambda: query.neighbors(arguments["entity_id"], arguments.get("depth", 1), arguments.get("direction", "both")),
        "fcc_graph_impact": lambda: query.impact(arguments["entity_ids"]),
        "fcc_graph_path": lambda: query.path(arguments["source"], arguments["target"]),
        "fcc_graph_god_nodes": lambda: query.god_nodes(arguments.get("top_n", 10), arguments.get("community")),
        "fcc_graph_community": lambda: query.community(arguments["entity_id"]),
        "fcc_graph_entity": lambda: query.entity(arguments["entity_id"]),
        "fcc_graph_stats": lambda: query.stats(),
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
            continue
        response = _handle_request(request)
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
