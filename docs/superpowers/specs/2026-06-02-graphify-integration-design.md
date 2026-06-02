# Graphify Knowledge Graph Integration — Design Spec

**Date:** 2026-06-02
**Status:** Design approved, pending implementation plan

## Overview

Integrate Graphify (MIT-licensed, 58k★) as SEPCC's knowledge graph layer. Graphify
parses code (33 languages via tree-sitter AST) and unstructured content into a
structured graph with entities, relations, communities, and intent annotations.
SEPCC wraps it in a thin FCC-native layer (`core/graph/`) that loads the graph
into SQLite, provides graph traversal query tools, injects structural summaries
at session start, matches entities in user prompts, and preserves graph anchors
through compaction and handoff — giving agents pre-computed codebase
understanding without re-reading the entire codebase every session.

## Architecture

### Component Map

```
core/graph/
├── __init__.py          # Public API: GraphQuery, GraphStore, context injectors
├── loader.py            # graphify's graph.json → in-memory + SQLite
├── store.py             # SQLite schema: entities, relations, communities, FTS5
├── query.py             # Graph traversal: neighbors, impact, path, gods, search
└── context.py           # Build injection strings for hooks

scripts/graph/
└── mcp_server.py        # MCP stdio server: fcc_graph_* tools

scripts/hooks/
├── session_start.py      # MODIFIED: inject structural summary
├── user_prompt_submit.py # MODIFIED: inject entity matches
└── precompact.py         # MODIFIED: inject structural anchors

core/context/
└── handoff.py            # MODIFIED: include structural context section

cli/
├── bootstrap_context.py  # MODIFIED: --install-graphify flag
└── context_doctor.py     # MODIFIED: graph health checks

.fcc/
├── graph/                # graphify output directory
│   ├── graph.json        # Source of truth (git-tracked or gitignored)
│   └── GRAPH_REPORT.md   # Human-readable highlights
└── router.yml            # MODIFIED: graph-informed routing rules
```

**15 files: 8 new, 7 modified, zero new Python dependencies.**

### Component Responsibilities

**`loader.py`** — Ingests graphify's `graph.json`:
- Validates the schema
- Loads entities, relations, communities into `GraphStore`
- `load_graph(root: Path) -> GraphStore` — main entry point
- `graphify_available() -> bool` — checks if `graphify` is on PATH (via `shutil.which`)
- `graph_path(root: Path) -> Path` — returns `.fcc/graph/graph.json` path
- Raises `GraphLoadError` on malformed/missing data

**`store.py`** — SQLite-backed graph persistence:
- Tables: `entities`, `relations`, `communities`, `entity_fts` (FTS5)
- Indexes on name, type, file, community, source_id, target_id
- Handles `clear()` + reload for incremental updates
- One class: `GraphStore(root: Path)`

**`query.py`** — Graph traversal operations:
- `neighbors(entity_id, depth, direction)` — N-hop traversal
- `impact(entity_ids)` — transitive closure with risk assessment
- `path(source, target)` — shortest dependency path
- `god_nodes(top_n, community)` — centrality ranking
- `search(query, top_n)` — FTS5 full-text search
- `community(entity_id)` — membership + peers
- `entity(entity_id)` — full detail lookup

**`context.py`** — Builds injection strings for hooks:
- `build_session_bootstrap(graph, task_hint, changed_files, token_budget)`
- `build_task_injection(graph, user_message, token_budget)`
- `build_structural_anchors(graph)`
- `build_handoff_context(graph)`

**Modified hooks** — One added call each, preserving all existing behavior:
- `session_start.py`: `build_session_bootstrap()` appended to payload
- `user_prompt_submit.py`: `build_task_injection()` added to payload tuple
- `precompact.py`: `build_structural_anchors()` appended to preserved facts

**`handoff.py`** — `regenerate_handoff()` gains a `## Structural Context` section.

**`bootstrap_context.py`** — `--install-graphify` flag: installs graphify, builds
initial graph, registers MCP server, installs auto-rebuild git hook.

**`context_doctor.py`** — Graph health checks: missing, stale, orphan edges,
community coverage, file size.

**`router.yml`** — Graph-informed routing rules. The `route-task` skill
reads the graph to evaluate these rules by calling `GraphQuery` methods:
centrality-based, community-size, impact-radius, unknown-entity detection.
The graph query is read-only and of zero cost to the hook budget since it
runs inside the skill, not inside a hook.

## Data Flow

### Build Flow (once, on bootstrap or explicit rebuild)

```
graphify . --output .fcc/graph/
       │
       ▼
.fcc/graph/graph.json  (source of truth)
       │
       ▼
load_graph(root)
  ├─ Validates schema
  ├─ Inserts entities, relations, communities
  ├─ Populates FTS5 index
  └─ Returns GraphStore
```

### Session Start Flow

```
SessionStart hook
  ├─ Existing: CLAUDE.md, CLAUDE.local.md, handoff, agent-runtime
  └─ NEW: if .fcc/graph/graph.json exists:
       build_session_bootstrap() → community overview + god nodes + change summary
       Inject as "## Project Structure" (~400-600 chars)
```

### User Prompt Flow

```
UserPromptSubmit hook
  ├─ Existing: enhancement, naming, routing hints, debugger pipeline
  └─ NEW: if graph available:
       extract_terms(prompt) → search graph → build_task_injection()
       Inject: "[Graph Context] Matched entities: ..." (~150-250 chars)
```

### Agent Query Flow (during session, via MCP tools)

```
Agent calls fcc_graph_impact(entity_id)
  → query.impact([entity_id])
  → Returns: {affected_entities, estimated_risk, files_touched, communities}
```

### PreCompact Flow

```
PreCompact hook
  ├─ Existing: Must Not Forget + Current State
  └─ NEW: build_structural_anchors()
       Inject: "## Structural Anchors: communities, god nodes, graph version"
       These survive compaction.
```

### Handoff Flow

```
regenerate_handoff() adds:
  "## Structural Context
   - Primary communities, modified god nodes, impact radius, graph version"
```

## MCP Server Tools

Registered in `.mcp.json` as `fcc-graph` (alongside Token Savior):

| Tool | Parameters | Returns |
|------|-----------|---------|
| `fcc_graph_search` | query, top_n | Entity[] |
| `fcc_graph_neighbors` | entity_id, depth, direction | {entity, dependencies, dependents, peers} |
| `fcc_graph_impact` | entity_ids | {affected_entities, estimated_risk, files_touched} |
| `fcc_graph_path` | source, target | PathStep[] |
| `fcc_graph_god_nodes` | top_n, community? | Entity[] |
| `fcc_graph_community` | entity_id | {community, peers, size} |
| `fcc_graph_entity` | entity_id | Entity |
| `fcc_graph_diff` | since: "last-session" or commit hash (7+ chars) | {new, removed, modified} |
| `fcc_graph_stats` | (none) | {entity_count, relation_count, community_count, graph_version} |

## Graph Schema (from graphify, loaded by SEPCC)

graphify produces a single `graph.json`:

```json
{
  "nodes": [
    {
      "id": "src/auth/manager.py::AuthManager",
      "type": "class",
      "file": "src/auth/manager.py",
      "line": 42,
      "name": "AuthManager",
      "community": "auth-infra",
      "centrality": 0.87,
      "metadata": {
        "docstring": "Central auth state machine...",
        "intents": ["HACK: mutates global state"]
      }
    }
  ],
  "edges": [
    {
      "source": "src/api/client.py::ApiClient",
      "target": "src/auth/manager.py::AuthManager",
      "type": "CALLS",
      "confidence": "EXTRACTED"
    }
  ],
  "communities": [
    {
      "id": "auth-infra",
      "label": "Authentication & Identity",
      "nodes": ["..."],
      "central_nodes": ["AuthManager"]
    }
  ]
}
```

SEPCC loads this into SQLite tables mirroring this structure.

## SQLite Schema

```sql
CREATE TABLE entities (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    file TEXT,
    line INTEGER,
    community TEXT,
    centrality REAL,
    docstring TEXT,
    intents TEXT,
    metadata TEXT
);

CREATE TABLE relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL REFERENCES entities(id),
    target_id TEXT NOT NULL REFERENCES entities(id),
    type TEXT NOT NULL,
    confidence TEXT NOT NULL,
    metadata TEXT
);

CREATE TABLE communities (
    id TEXT PRIMARY KEY,
    label TEXT,
    size INTEGER,
    central_nodes TEXT
);

CREATE VIRTUAL TABLE entity_fts USING fts5(
    name, docstring, intents,
    content='entities', content_rowid='rowid'
);
```

## Injection Formats

### Session Bootstrap (~400-600 chars)

```
## Project Structure
Primary domains:
  • auth-infra (23 nodes) — Authentication, sessions, token management
  • api-gateway (18 nodes) — Request routing, middleware, rate limiting
  • data-layer (31 nodes) — Database access, migrations, caching

Key abstractions:
  • AuthManager (god, 0.92 centrality, 23 connections)
  • ApiGateway (god, 0.87 centrality, 18 connections)
  • DatabasePool (god, 0.81 centrality, 31 connections)

Active: feat/add-2fa (2 files changed, 28 entities affected)
  Primary community: auth-infra
```

### Task Injection (~150-250 chars)

```
[Graph Context]
Matched entities:
  • AuthManager (src/auth/manager.py:42) — god node, 23 connections
    Community: auth-infra
    Depends on: ErrorFormatter, TokenValidator, SessionStore
    Called by: LoginFlow, SignupFlow, PasswordReset (and 14 others)
```

### Structural Anchors (for PreCompact, ~150 chars)

```
## Structural Anchors
- Primary communities: auth-infra (23), api-gateway (18)
- God nodes touched: AuthManager, ErrorFormatter
- Graph version: f3a2b1c (2026-06-02 14:32 UTC)
```

## Error Handling

| Scenario | Behavior |
|----------|----------|
| No graph exists | All injections return empty. Graph is enhancement, not requirement. |
| Graph stale vs HEAD | Doctor warns. Load anyway. Injection notes: "Graph may be outdated." |
| graph.json malformed | GraphLoadError raised. Hook catches, logs warning, returns empty. |
| graph.json > 50MB | Doctor warns. Load with 5s timeout; skip on timeout with warning. |
| graphify not installed | Bootstrap reports. All code checks `graphify_available()` first. |
| Entity not found | Query returns None/empty. MCP returns structured `{error: "not_found"}`. |
| git binary missing | Change detection skips. Injection omits change summary. |
| FTS5 unavailable | `search()` falls back to `LIKE '%query%'`. Logs warning. |
| Race: graph rebuild during session | Store holds old version until next reload. Injection notes version. |

## Testing Strategy

### Layer 1: Store & Schema (unit)
- Table creation, entity/relation/community insertion, upsert, FTS5 queries, clear+reload

### Layer 2: Query Operations (unit)
- neighbors (in/out/both, depth 1/2), impact (risk levels), path (direct/indirect/disconnected), god_nodes (all/scoped), search (exact/fuzzy/no-match), community, entity

### Layer 3: Context Injection (unit)
- Session bootstrap format, task injection matching, structural anchors, handoff context, token budgets

### Layer 4: Graphify Loader (integration)
- Valid graph load, missing/malformed files, minimal graph, entity ID format parsing

### Layer 5: Hook Integration (integration)
- Session start includes structure, no-graph no-crash, entity injection in prompts, precompact anchors, budget compliance

### Layer 6: Context Doctor (unit)
- Missing graph warning, stale graph warning, healthy check, orphan edges, file size

### Layer 7: End-to-End (live)
- Full build → load → query, simulated session, incremental rebuild

## Non-Goals (v1)

- Live graph updates during sessions (graph is pre-computed, no mutation)
- Cross-repository graph merging
- Custom entity extraction beyond graphify's output
- Graph visualization (graphify's graph.html handles this)
- Automatic merge of fixer branches
- Graph-based subagent dispatch (uses existing subagent system)
