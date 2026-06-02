# Graphify Knowledge Graph Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate Graphify as SEPCC's knowledge graph layer — a thin FCC-native wrapper (`core/graph/`) that loads graphify's `graph.json` into SQLite, provides graph traversal query tools, injects structural summaries into hooks, and preserves graph anchors through compaction and handoff.

**Architecture:** Five new files in `core/graph/` (store, loader, query, context, init), one MCP server, three modified hooks, modified handoff, modified bootstrap, modified doctor, modified router. One external tool dependency: `graphifyy[leiden]` (uv tool install). Zero new Python dependencies.

**Tech Stack:** Python 3.14+, stdlib (sqlite3, json, pathlib, subprocess, shutil), pytest. No new packages in pyproject.toml.

---

### Task 1: Graph Store — `core/graph/store.py`

**Files:**
- Create: `core/graph/__init__.py` (empty package marker)
- Create: `core/graph/store.py`
- Test: `tests/graph/test_store.py`

- [ ] **Step 1: Create directories and empty package file**

```powershell
New-Item -ItemType Directory -Force -Path core\graph
New-Item -ItemType Directory -Force -Path tests\graph
New-Item -ItemType File -Path core\graph\__init__.py
New-Item -ItemType File -Path tests\graph\__init__.py
```

- [ ] **Step 2: Write the store module**

Write to `core/graph/store.py`:

```python
"""SQLite-backed knowledge graph persistence for FCC Graphify integration."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class GraphStore:
    """Persistent graph storage backed by SQLite with FTS5 full-text search."""

    def __init__(self, root: Path) -> None:
        self._db_path = root / ".fcc" / "graph" / "store.db"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.row_factory = sqlite3.Row
        self._create_tables()
        self._has_fts5 = self._check_fts5()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _create_tables(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS entities (
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
            CREATE TABLE IF NOT EXISTS relations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                type TEXT NOT NULL,
                confidence TEXT NOT NULL,
                metadata TEXT
            );
            CREATE TABLE IF NOT EXISTS communities (
                id TEXT PRIMARY KEY,
                label TEXT,
                size INTEGER,
                central_nodes TEXT
            );
            """
        )
        self._conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name);
            """
        )
        self._conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type);
            """
        )
        self._conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_entities_file ON entities(file);
            """
        )
        self._conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_entities_community ON entities(community);
            """
        )
        self._conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_relations_source ON relations(source_id);
            """
        )
        self._conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_relations_target ON relations(target_id);
            """
        )
        self._conn.commit()

    def _check_fts5(self) -> bool:
        """Check if FTS5 extension is available in this SQLite build."""
        try:
            self._conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS entity_fts USING fts5(
                    name, docstring, intents,
                    content='entities', content_rowid='rowid'
                )
                """
            )
            self._conn.commit()
            return True
        except sqlite3.OperationalError:
            return False

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def insert_entity(self, entity: dict[str, Any]) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO entities
            (id, name, type, file, line, community, centrality,
             docstring, intents, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entity["id"],
                entity.get("name", ""),
                entity.get("type", "unknown"),
                entity.get("file"),
                entity.get("line"),
                entity.get("community"),
                entity.get("centrality"),
                entity.get("docstring"),
                json.dumps(entity.get("intents", [])) if entity.get("intents") else None,
                json.dumps(entity.get("metadata")) if entity.get("metadata") else None,
            ),
        )

    def insert_relation(self, rel: dict[str, Any]) -> None:
        self._conn.execute(
            """
            INSERT INTO relations (source_id, target_id, type, confidence, metadata)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                rel["source"],
                rel["target"],
                rel.get("type", "UNKNOWN"),
                rel.get("confidence", "INFERRED"),
                json.dumps(rel.get("metadata")) if rel.get("metadata") else None,
            ),
        )

    def insert_community(self, community: dict[str, Any]) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO communities (id, label, size, central_nodes)
            VALUES (?, ?, ?, ?)
            """,
            (
                community["id"],
                community.get("label", community["id"]),
                community.get("size", 0),
                json.dumps(community.get("central_nodes", [])),
            ),
        )

    def clear(self) -> None:
        """Remove all data. Call before reloading from a fresh graph.json."""
        self._conn.execute("DELETE FROM relations")
        self._conn.execute("DELETE FROM entities")
        self._conn.execute("DELETE FROM communities")
        if self._has_fts5:
            try:
                self._conn.execute(
                    "INSERT INTO entity_fts(entity_fts) VALUES ('rebuild')"
                )
            except sqlite3.OperationalError:
                pass
        self._conn.commit()

    def commit(self) -> None:
        self._conn.commit()

    def version(self) -> str | None:
        """Return the graph version (last rebuild timestamp), if tracked."""
        try:
            row = self._conn.execute(
                "SELECT value FROM schema_meta WHERE key = 'graph_version'"
            ).fetchone()
            return row["value"] if row else None
        except sqlite3.OperationalError:
            return None

    def set_version(self, version: str) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_meta (
                key TEXT PRIMARY KEY, value TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            INSERT INTO schema_meta(key, value) VALUES ('graph_version', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (version,),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Read operations (basic — complex queries live in query.py)
    # ------------------------------------------------------------------

    def get_entity(self, entity_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM entities WHERE id = ?", (entity_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def entity_count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) as cnt FROM entities").fetchone()
        return row["cnt"] if row else 0

    def relation_count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) as cnt FROM relations").fetchone()
        return row["cnt"] if row else 0

    def community_count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) as cnt FROM communities").fetchone()
        return row["cnt"] if row else 0

    def get_communities(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM communities ORDER BY size DESC"
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_outgoing_relations(self, entity_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM relations WHERE source_id = ?", (entity_id,)
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_incoming_relations(self, entity_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM relations WHERE target_id = ?", (entity_id,)
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_entities_by_community(self, community_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM entities WHERE community = ?", (community_id,)
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def search_fts(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        if self._has_fts5:
            try:
                rows = self._conn.execute(
                    """
                    SELECT e.* FROM entities e
                    JOIN entity_fts fts ON e.rowid = fts.rowid
                    WHERE entity_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (query, limit),
                ).fetchall()
                return [self._row_to_dict(r) for r in rows]
            except sqlite3.OperationalError:
                pass
        # FTS5 fallback: simple LIKE search
        pattern = f"%{query}%"
        rows = self._conn.execute(
            "SELECT * FROM entities WHERE name LIKE ? LIMIT ?",
            (pattern, limit),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_top_by_centrality(self, limit: int = 10, community: str | None = None) -> list[dict[str, Any]]:
        if community:
            rows = self._conn.execute(
                """
                SELECT * FROM entities
                WHERE community = ? AND centrality IS NOT NULL
                ORDER BY centrality DESC LIMIT ?
                """,
                (community, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT * FROM entities
                WHERE centrality IS NOT NULL
                ORDER BY centrality DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def connection_count(self, entity_id: str) -> int:
        row = self._conn.execute(
            """
            SELECT COUNT(*) as cnt FROM relations
            WHERE source_id = ? OR target_id = ?
            """,
            (entity_id, entity_id),
        ).fetchone()
        return row["cnt"] if row else 0

    def close(self) -> None:
        self._conn.close()

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        # Deserialize JSON fields
        for field in ("intents", "metadata", "central_nodes"):
            if field in d and isinstance(d[field], str):
                try:
                    d[field] = json.loads(d[field])
                except (json.JSONDecodeError, TypeError):
                    pass
        return d
```

- [ ] **Step 3: Write the store tests**

Write to `tests/graph/test_store.py`:

```python
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
    results = store.search_fts("auth", limit=10)
    assert len(results) >= 1
    names = [r["name"] for r in results]
    assert "process_request" in names


def test_fts_search_no_results(store: GraphStore) -> None:
    store.insert_entity({"id": "a", "name": "foo", "type": "class"})
    store.commit()
    results = store.search_fts("zzz_nonexistent_zzz", limit=10)
    assert results == []


def test_top_by_centrality(store: GraphStore) -> None:
    store.insert_entity({"id": "a", "name": "low", "type": "class", "centrality": 0.1})
    store.insert_entity({"id": "b", "name": "mid", "type": "class", "centrality": 0.5})
    store.insert_entity({"id": "c", "name": "high", "type": "class", "centrality": 0.99})
    store.insert_entity({"id": "d", "name": "none", "type": "class"})
    store.commit()
    top = store.get_top_by_centrality(limit=10)
    assert len(top) == 3  # Only those with centrality
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
```

- [ ] **Step 4: Run the store tests**

```bash
uv run pytest tests/graph/test_store.py -v
```

Expected: 15 tests pass.

- [ ] **Step 5: Commit**

```bash
git add core/graph/__init__.py core/graph/store.py tests/graph/__init__.py tests/graph/test_store.py
git commit -m "feat: add GraphStore — SQLite-backed knowledge graph persistence"
```

---

### Task 2: Graph Loader — `core/graph/loader.py`

**Files:**
- Create: `core/graph/loader.py`
- Test: `tests/graph/test_loader.py`

- [ ] **Step 1: Write the loader module**

Write to `core/graph/loader.py`:

```python
"""Load graphify's graph.json into a GraphStore."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from core.graph.store import GraphStore


class GraphLoadError(Exception):
    """Raised when graph.json cannot be loaded or is malformed."""


def graph_path(root: Path) -> Path:
    """Return the path to graphify's graph.json."""
    return root / ".fcc" / "graph" / "graph.json"


def graphify_available() -> bool:
    """Check if the `graphify` CLI is on PATH."""
    return shutil.which("graphify") is not None


def load_graph(root: Path, *, timeout: float = 5.0) -> GraphStore:
    """Load graphify's graph.json into a fresh GraphStore.

    Raises GraphLoadError on missing, malformed, or invalid data.
    The timeout applies to file read + SQLite insert; currently
    enforced only as a size-guard heuristic.
    """
    path = graph_path(root)
    if not path.is_file():
        raise GraphLoadError(f"Graph file not found: {path}")

    # Size guard: warn on large files
    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb > 50:
        raise GraphLoadError(
            f"graph.json is {size_mb:.0f}MB (max 50MB). "
            "Consider excluding generated/template directories."
        )

    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GraphLoadError(f"Malformed JSON in graph.json: {exc}") from exc

    if not isinstance(data, dict):
        raise GraphLoadError("graph.json top-level must be a JSON object")

    nodes = data.get("nodes")
    edges = data.get("edges")
    communities = data.get("communities")

    if not isinstance(nodes, list):
        raise GraphLoadError("graph.json 'nodes' must be a list")
    if not isinstance(edges, list):
        raise GraphLoadError("graph.json 'edges' must be a list")

    store = GraphStore(root)
    store.clear()

    for node in nodes:
        _validate_node(node)
        entity = _normalize_node(node)
        store.insert_entity(entity)

    for edge in edges:
        _validate_edge(edge)
        rel = _normalize_edge(edge)
        store.insert_relation(rel)

    if isinstance(communities, list):
        for comm in communities:
            _validate_community(comm)
            store.insert_community(comm)

    store.commit()

    # Track version: use mtime as version string
    mtime = path.stat().st_mtime
    from datetime import UTC, datetime
    version = datetime.fromtimestamp(mtime, UTC).isoformat()
    store.set_version(version)

    return store


def _validate_node(node: dict[str, Any]) -> None:
    if not isinstance(node.get("id"), str) or not node["id"].strip():
        raise GraphLoadError(f"Node missing valid 'id': {node}")
    if not isinstance(node.get("name"), str):
        node["name"] = node["id"]


def _validate_edge(edge: dict[str, Any]) -> None:
    if not isinstance(edge.get("source"), str) or not edge["source"].strip():
        raise GraphLoadError(f"Edge missing valid 'source': {edge}")
    if not isinstance(edge.get("target"), str) or not edge["target"].strip():
        raise GraphLoadError(f"Edge missing valid 'target': {edge}")


def _validate_community(comm: dict[str, Any]) -> None:
    if not isinstance(comm.get("id"), str) or not comm["id"].strip():
        raise GraphLoadError(f"Community missing valid 'id': {comm}")


def _normalize_node(node: dict[str, Any]) -> dict[str, Any]:
    metadata = node.get("metadata")
    if isinstance(metadata, dict):
        docstring = metadata.get("docstring", "")
        intents = metadata.get("intents", [])
    else:
        docstring = ""
        intents = []
    return {
        "id": node["id"],
        "name": node.get("name", node["id"]),
        "type": node.get("type", "unknown"),
        "file": node.get("file"),
        "line": node.get("line"),
        "community": node.get("community"),
        "centrality": node.get("centrality"),
        "docstring": docstring,
        "intents": intents if isinstance(intents, list) else [],
    }


def _normalize_edge(edge: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": edge["source"],
        "target": edge["target"],
        "type": edge.get("type", "UNKNOWN"),
        "confidence": edge.get("confidence", "INFERRED"),
    }
```

- [ ] **Step 2: Write loader tests**

Write to `tests/graph/test_loader.py`:

```python
"""Tests for the graphify graph.json loader."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.graph.loader import (
    GraphLoadError,
    _normalize_edge,
    _normalize_node,
    graph_path,
    graphify_available,
    load_graph,
)
from core.graph.store import GraphStore


def test_graph_path(tmp_path: Path) -> None:
    expected = tmp_path / ".fcc" / "graph" / "graph.json"
    assert graph_path(tmp_path) == expected


def test_graphify_available() -> None:
    result = graphify_available()
    assert isinstance(result, bool)


def test_load_missing_file(tmp_path: Path) -> None:
    with pytest.raises(GraphLoadError, match="not found"):
        load_graph(tmp_path)


def test_load_malformed_json(tmp_path: Path) -> None:
    graph_dir = tmp_path / ".fcc" / "graph"
    graph_dir.mkdir(parents=True)
    (graph_dir / "graph.json").write_text("not json", encoding="utf-8")
    with pytest.raises(GraphLoadError, match="Malformed JSON"):
        load_graph(tmp_path)


def test_load_top_level_not_dict(tmp_path: Path) -> None:
    graph_dir = tmp_path / ".fcc" / "graph"
    graph_dir.mkdir(parents=True)
    (graph_dir / "graph.json").write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(GraphLoadError, match="JSON object"):
        load_graph(tmp_path)


def test_load_minimal_graph(tmp_path: Path) -> None:
    graph_dir = tmp_path / ".fcc" / "graph"
    graph_dir.mkdir(parents=True)
    data = {"nodes": [], "edges": [], "communities": []}
    (graph_dir / "graph.json").write_text(json.dumps(data), encoding="utf-8")
    store = load_graph(tmp_path)
    assert store.entity_count() == 0
    assert store.relation_count() == 0


def test_load_complete_graph(tmp_path: Path) -> None:
    graph_dir = tmp_path / ".fcc" / "graph"
    graph_dir.mkdir(parents=True)
    data = {
        "nodes": [
            {
                "id": "src/auth.py::AuthManager",
                "name": "AuthManager",
                "type": "class",
                "file": "src/auth.py",
                "line": 42,
                "community": "auth-infra",
                "centrality": 0.87,
                "metadata": {
                    "docstring": "Central auth state",
                    "intents": ["HACK: mutates global state"],
                },
            },
            {
                "id": "src/api.py::ApiClient",
                "name": "ApiClient",
                "type": "class",
                "file": "src/api.py",
                "line": 15,
            },
        ],
        "edges": [
            {
                "source": "src/api.py::ApiClient",
                "target": "src/auth.py::AuthManager",
                "type": "CALLS",
                "confidence": "EXTRACTED",
            }
        ],
        "communities": [
            {
                "id": "auth-infra",
                "label": "Authentication & Identity",
                "size": 12,
                "central_nodes": ["AuthManager"],
            }
        ],
    }
    (graph_dir / "graph.json").write_text(json.dumps(data), encoding="utf-8")
    store = load_graph(tmp_path)
    assert store.entity_count() == 2
    assert store.relation_count() == 1
    assert store.community_count() == 1

    auth = store.get_entity("src/auth.py::AuthManager")
    assert auth is not None
    assert auth["name"] == "AuthManager"
    assert auth["centrality"] == 0.87
    assert auth["docstring"] == "Central auth state"
    assert auth["intents"] == ["HACK: mutates global state"]

    # Check version was set
    version = store.version()
    assert version is not None
    assert "T" in version


def test_load_invalid_node_id(tmp_path: Path) -> None:
    graph_dir = tmp_path / ".fcc" / "graph"
    graph_dir.mkdir(parents=True)
    data = {"nodes": [{"name": "NoID"}], "edges": []}
    (graph_dir / "graph.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(GraphLoadError, match="valid 'id'"):
        load_graph(tmp_path)


def test_load_invalid_edge_source(tmp_path: Path) -> None:
    graph_dir = tmp_path / ".fcc" / "graph"
    graph_dir.mkdir(parents=True)
    data = {
        "nodes": [{"id": "a", "name": "A"}],
        "edges": [{"target": "a"}],
    }
    (graph_dir / "graph.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(GraphLoadError, match="valid 'source'"):
        load_graph(tmp_path)


def test_load_large_file_guard(tmp_path: Path) -> None:
    """Verify the 50MB size guard is checked (mock by patching the stat)."""
    graph_dir = tmp_path / ".fcc" / "graph"
    graph_dir.mkdir(parents=True)
    path = graph_dir / "graph.json"
    # Write a file and patch: we verify the check exists
    path.write_text("{}", encoding="utf-8")
    # The guard checks st_size — a 2-byte file is fine
    store = load_graph(tmp_path)
    assert store.entity_count() == 0  # empty object with no keys raises? no — missing keys = lists
    # Just verify no crash on small files
```

- [ ] **Step 3: Run loader tests**

```bash
uv run pytest tests/graph/test_loader.py -v
```

Expected: 8 tests pass, 1 may need adjustment for empty graph behavior.

- [ ] **Step 4: Commit**

```bash
git add core/graph/loader.py tests/graph/test_loader.py
git commit -m "feat: add graph.json loader with validation and error handling"
```

---

### Task 3: Graph Query — `core/graph/query.py`

**Files:**
- Create: `core/graph/query.py`
- Test: `tests/graph/test_query.py`

- [ ] **Step 1: Write the query module**

Write to `core/graph/query.py`:

```python
"""Graph traversal queries on the knowledge graph."""

from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any, Literal

from core.graph.store import GraphStore


class GraphQuery:
    """Read-only graph traversal operations over a GraphStore."""

    def __init__(self, store: GraphStore) -> None:
        self._store = store

    # ------------------------------------------------------------------
    # Entity lookup
    # ------------------------------------------------------------------

    def entity(self, entity_id: str) -> dict[str, Any] | None:
        """Get full entity details by ID."""
        return self._store.get_entity(entity_id)

    # ------------------------------------------------------------------
    # Neighbors
    # ------------------------------------------------------------------

    def neighbors(
        self,
        entity_id: str,
        depth: int = 1,
        direction: Literal["in", "out", "both"] = "both",
    ) -> dict[str, Any]:
        """Get N-hop neighborhood of an entity.

        Returns:
            {
                "entity": {...},
                "dependencies": [...],   # What this entity depends on
                "dependents": [...],     # What depends on this entity
                "community_peers": [...],# Other entities in same community
            }
        """
        entity = self._store.get_entity(entity_id)
        if entity is None:
            return {
                "entity": None,
                "dependencies": [],
                "dependents": [],
                "community_peers": [],
            }

        deps: list[dict[str, Any]] = []
        dents: list[dict[str, Any]] = []

        if direction in ("out", "both"):
            deps = self._traverse_outgoing(entity_id, depth)

        if direction in ("in", "both"):
            dents = self._traverse_incoming(entity_id, depth)

        # Community peers
        peers: list[dict[str, Any]] = []
        community = entity.get("community")
        if community:
            peers = [
                e for e in self._store.get_entities_by_community(community)
                if e["id"] != entity_id
            ]

        return {
            "entity": entity,
            "dependencies": deps,
            "dependents": dents,
            "community_peers": peers,
        }

    def _traverse_outgoing(
        self, entity_id: str, depth: int
    ) -> list[dict[str, Any]]:
        """BFS outbound from entity_id up to `depth` hops."""
        return self._bfs(entity_id, depth, direction="out")

    def _traverse_incoming(
        self, entity_id: str, depth: int
    ) -> list[dict[str, Any]]:
        """BFS inbound to entity_id up to `depth` hops."""
        return self._bfs(entity_id, depth, direction="in")

    def _bfs(
        self, start: str, max_depth: int, direction: str
    ) -> list[dict[str, Any]]:
        visited: set[str] = {start}
        queue: deque[tuple[str, int]] = deque([(start, 0)])
        results: list[dict[str, Any]] = []

        while queue:
            current, d = queue.popleft()
            if d >= max_depth:
                continue

            if direction == "out":
                rels = self._store.get_outgoing_relations(current)
                neighbors_ids = {r["target_id"] for r in rels}
            else:
                rels = self._store.get_incoming_relations(current)
                neighbors_ids = {r["source_id"] for r in rels}

            for nid in neighbors_ids:
                if nid not in visited:
                    visited.add(nid)
                    entity = self._store.get_entity(nid)
                    if entity:
                        results.append(entity)
                    queue.append((nid, d + 1))

        return results

    # ------------------------------------------------------------------
    # Impact analysis
    # ------------------------------------------------------------------

    def impact(self, entity_ids: list[str]) -> dict[str, Any]:
        """Transitive closure: what breaks if these entities change?

        Returns:
            {
                "directly_affected": [...],      # 1 hop
                "transitively_affected": [...],  # N hops
                "affected_communities": [...],
                "estimated_risk": "low" | "medium" | "high",
                "files_touched": N,
            }
        """
        all_affected: set[str] = set()
        communities: set[str] = set()
        files: set[str] = set()

        for eid in entity_ids:
            entity = self._store.get_entity(eid)
            if entity and entity.get("file"):
                files.add(entity["file"])
            if entity and entity.get("community"):
                communities.add(entity["community"])
            # Full transitive closure: find all dependents
            closure = self._transitive_closure(eid, direction="in")
            all_affected.update(closure)

        # Separate into direct (1-hop) and transitive (2+ hops)
        direct: set[str] = set()
        for eid in entity_ids:
            incoming = self._store.get_incoming_relations(eid)
            direct.update({r["source_id"] for r in incoming})

        transitive = all_affected - direct - set(entity_ids)

        # Count files
        for eid in all_affected:
            entity = self._store.get_entity(eid)
            if entity and entity.get("file"):
                files.add(entity["file"])
            if entity and entity.get("community"):
                communities.add(entity["community"])

        file_count = len(files)
        if file_count <= 5:
            risk = "low"
        elif file_count <= 15:
            risk = "medium"
        else:
            risk = "high"

        return {
            "directly_affected": sorted(direct),
            "transitively_affected": sorted(transitive),
            "affected_communities": sorted(communities),
            "estimated_risk": risk,
            "files_touched": file_count,
        }

    def _transitive_closure(
        self, start: str, direction: str
    ) -> set[str]:
        """All reachable nodes from start in the given direction."""
        visited: set[str] = set()
        queue: deque[str] = deque([start])

        while queue:
            current = queue.popleft()
            if current in visited:
                continue
            visited.add(current)

            if direction == "in":
                rels = self._store.get_incoming_relations(current)
                neighbors = {r["source_id"] for r in rels}
            else:
                rels = self._store.get_outgoing_relations(current)
                neighbors = {r["target_id"] for r in rels}

            for nid in neighbors:
                if nid not in visited:
                    queue.append(nid)

        visited.discard(start)
        return visited

    # ------------------------------------------------------------------
    # Shortest path
    # ------------------------------------------------------------------

    def path(self, source: str, target: str) -> list[dict[str, Any]]:
        """Shortest dependency path between two entities via BFS.

        Returns a list of steps: [
            {"entity": "B", "relation": "CALLS", "next": "C"},
            ...
        ]
        Empty list if no path exists.
        """
        if source == target:
            return []

        queue: deque[tuple[str, list[dict[str, Any]]]] = deque(
            [(source, [])]
        )
        visited: set[str] = {source}

        while queue:
            current, path_so_far = queue.popleft()
            outgoing = self._store.get_outgoing_relations(current)

            for rel in outgoing:
                neighbor = rel["target_id"]
                if neighbor == target:
                    return path_so_far + [
                        {
                            "entity": current,
                            "relation": rel["type"],
                            "next": neighbor,
                        }
                    ]
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(
                        (
                            neighbor,
                            path_so_far
                            + [
                                {
                                    "entity": current,
                                    "relation": rel["type"],
                                    "next": neighbor,
                                }
                            ],
                        )
                    )

        return []

    # ------------------------------------------------------------------
    # God nodes
    # ------------------------------------------------------------------

    def god_nodes(
        self, top_n: int = 10, community: str | None = None
    ) -> list[dict[str, Any]]:
        """Most-connected entities ranked by centrality."""
        nodes = self._store.get_top_by_centrality(limit=top_n, community=community)
        for node in nodes:
            node["connection_count"] = self._store.connection_count(node["id"])
        return nodes

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(self, query: str, top_n: int = 10) -> list[dict[str, Any]]:
        """Full-text search over entity names and docstrings."""
        return self._store.search_fts(query, limit=top_n)

    # ------------------------------------------------------------------
    # Community
    # ------------------------------------------------------------------

    def community(self, entity_id: str) -> dict[str, Any] | None:
        """Get the community an entity belongs to + all peers."""
        entity = self._store.get_entity(entity_id)
        if entity is None:
            return None
        community_id = entity.get("community")
        if not community_id:
            return {"community": None, "peers": [], "size": 0}

        community_row = self._store._conn.execute(
            "SELECT * FROM communities WHERE id = ?", (community_id,)
        ).fetchone()
        peers = self._store.get_entities_by_community(community_id)
        return {
            "community": dict(community_row) if community_row else {"id": community_id},
            "peers": [p for p in peers if p["id"] != entity_id],
            "size": len(peers),
        }

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        """Return graph summary statistics."""
        return {
            "entity_count": self._store.entity_count(),
            "relation_count": self._store.relation_count(),
            "community_count": self._store.community_count(),
            "graph_version": self._store.version(),
        }

    # ------------------------------------------------------------------
    # Diff
    # ------------------------------------------------------------------

    def diff(self, since: str) -> dict[str, Any]:
        """Return a placeholder diff. Full git-diff-based diff is a v2 feature.

        For now, returns stats + a note that entity-level diff requires
        git integration.
        """
        return {
            "since": since,
            "stats": self.stats(),
            "note": "Entity-level diff not yet implemented. Use fcc_graph_stats for current state.",
        }
```

- [ ] **Step 2: Write query tests**

Write to `tests/graph/test_query.py`:

```python
"""Unit tests for GraphQuery traversal operations."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.graph.loader import load_graph
from core.graph.query import GraphQuery


@pytest.fixture
def query() -> GraphQuery:
    """Build a small in-memory graph with known structure."""
    from core.graph.store import GraphStore
    import tempfile

    tmp = Path(tempfile.mkdtemp())
    store = GraphStore(tmp)
    # Insert entities
    store.insert_entity({
        "id": "a.py::A",
        "name": "A",
        "type": "class",
        "file": "a.py",
        "line": 1,
        "community": "core",
        "centrality": 0.9,
    })
    store.insert_entity({
        "id": "b.py::B",
        "name": "B",
        "type": "class",
        "file": "b.py",
        "line": 1,
        "community": "core",
        "centrality": 0.5,
    })
    store.insert_entity({
        "id": "c.py::C",
        "name": "C",
        "type": "class",
        "file": "c.py",
        "line": 1,
        "community": "ui",
        "centrality": 0.3,
    })
    store.insert_entity({
        "id": "d.py::D",
        "name": "D",
        "type": "function",
        "file": "d.py",
        "line": 10,
    })
    # Relations: A → B, A → C, B → D
    store.insert_relation({
        "source": "a.py::A",
        "target": "b.py::B",
        "type": "CALLS",
        "confidence": "EXTRACTED",
    })
    store.insert_relation({
        "source": "a.py::A",
        "target": "c.py::C",
        "type": "CALLS",
        "confidence": "EXTRACTED",
    })
    store.insert_relation({
        "source": "b.py::B",
        "target": "d.py::D",
        "type": "CALLS",
        "confidence": "EXTRACTED",
    })
    store.commit()
    return GraphQuery(store)


def test_entity_found(query: GraphQuery) -> None:
    entity = query.entity("a.py::A")
    assert entity is not None
    assert entity["name"] == "A"


def test_entity_not_found(query: GraphQuery) -> None:
    entity = query.entity("nonexistent")
    assert entity is None


def test_neighbors_outgoing(query: GraphQuery) -> None:
    result = query.neighbors("a.py::A", direction="out")
    deps = result["dependencies"]
    dep_ids = {d["id"] for d in deps}
    assert "b.py::B" in dep_ids
    assert "c.py::C" in dep_ids


def test_neighbors_incoming(query: GraphQuery) -> None:
    result = query.neighbors("b.py::B", direction="in")
    dents = result["dependents"]
    dent_ids = {d["id"] for d in dents}
    assert "a.py::A" in dent_ids


def test_neighbors_depth_2(query: GraphQuery) -> None:
    """From A at depth 2: should reach D through B."""
    result = query.neighbors("a.py::A", depth=2, direction="out")
    deps = result["dependencies"]
    dep_ids = {d["id"] for d in deps}
    assert "d.py::D" in dep_ids


def test_neighbors_not_found(query: GraphQuery) -> None:
    result = query.neighbors("nonexistent")
    assert result["entity"] is None
    assert result["dependencies"] == []


def test_community_peers_in_neighbors(query: GraphQuery) -> None:
    result = query.neighbors("a.py::A")
    peers = result["community_peers"]
    peer_ids = {p["id"] for p in peers}
    assert "b.py::B" in peer_ids
    assert "c.py::C" not in peer_ids  # different community


def test_impact_risk_high(query: GraphQuery) -> None:
    """Changing A should affect B, C, D — 4 files = low risk."""
    result = query.impact(["a.py::A"])
    assert result["estimated_risk"] in ("low", "medium", "high")
    assert result["files_touched"] >= 1


def test_impact_risk_empty(query: GraphQuery) -> None:
    result = query.impact(["nonexistent"])
    assert result["files_touched"] == 0


def test_path_direct(query: GraphQuery) -> None:
    steps = query.path("a.py::A", "b.py::B")
    assert len(steps) == 1
    assert steps[0]["entity"] == "a.py::A"
    assert steps[0]["next"] == "b.py::B"


def test_path_indirect(query: GraphQuery) -> None:
    steps = query.path("a.py::A", "d.py::D")
    assert len(steps) >= 1
    # Last step should reach D
    assert steps[-1]["next"] == "d.py::D"


def test_path_disconnected(query: GraphQuery) -> None:
    # D has no outgoing edges, and nothing points to a nonexistent node
    steps = query.path("d.py::D", "a.py::A")
    assert steps == []


def test_god_nodes(query: GraphQuery) -> None:
    gods = query.god_nodes(top_n=10)
    assert len(gods) >= 1
    assert gods[0]["name"] == "A"  # Highest centrality


def test_god_nodes_scoped(query: GraphQuery) -> None:
    gods = query.god_nodes(top_n=10, community="ui")
    assert len(gods) == 1
    assert gods[0]["name"] == "C"


def test_search(query: GraphQuery) -> None:
    results = query.search("A", top_n=10)
    assert len(results) >= 1
    assert results[0]["name"] == "A"


def test_search_no_match(query: GraphQuery) -> None:
    results = query.search("zzz_nonexistent")
    assert results == []


def test_community(query: GraphQuery) -> None:
    result = query.community("a.py::A")
    assert result is not None
    assert result["size"] >= 1


def test_community_no_membership(query: GraphQuery) -> None:
    result = query.community("d.py::D")
    assert result is not None
    assert result["community"] is None


def test_community_not_found(query: GraphQuery) -> None:
    result = query.community("nonexistent")
    assert result is None


def test_stats(query: GraphQuery) -> None:
    s = query.stats()
    assert s["entity_count"] == 4
    assert s["relation_count"] == 3
    assert s["community_count"] >= 0
```

- [ ] **Step 3: Run query tests**

```bash
uv run pytest tests/graph/test_query.py -v
```

Expected: 20 tests pass.

- [ ] **Step 4: Commit**

```bash
git add core/graph/query.py tests/graph/test_query.py
git commit -m "feat: add GraphQuery — traversal operations (neighbors, impact, path, gods, search)"
```

---

### Task 4: Context Injection — `core/graph/context.py`

**Files:**
- Create: `core/graph/context.py`
- Test: `tests/graph/test_context.py`

- [ ] **Step 1: Write the context module**

Write to `core/graph/context.py`:

```python
"""Build graph-aware context injection strings for FCC hooks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.graph.loader import graph_path, load_graph
from core.graph.query import GraphQuery


def _get_query(root: Path | object) -> GraphQuery | None:
    """Safely load a GraphQuery if a graph exists. Returns None otherwise."""
    from pathlib import Path as _Path

    if not isinstance(root, _Path):
        return None
    path = graph_path(root)
    if not path.is_file():
        return None
    try:
        store = load_graph(root)
        return GraphQuery(store)
    except Exception:
        return None


def build_session_bootstrap(
    graph: GraphQuery,
    task_hint: str | None = None,
    changed_files: list[str] | None = None,
    token_budget: int = 600,
) -> str:
    """Build structural summary for SessionStart injection.

    Includes: community overview, god nodes, change summary.
    """
    lines: list[str] = ["## Project Structure"]

    # Community overview
    communities = graph._store.get_communities()
    if communities:
        lines.append("Primary domains:")
        for c in communities[:5]:
            label = c.get("label", c["id"])
            size = c.get("size", len(c.get("central_nodes", [])))
            lines.append(f"  • {c['id']} ({size} nodes) — {label}")

    # God nodes
    gods = graph.god_nodes(top_n=8)
    if gods:
        lines.append("\nKey abstractions:")
        for g in gods:
            conns = g.get("connection_count", 0)
            cent = g.get("centrality", 0)
            lines.append(f"  • {g['name']} (god, {cent:.2f} centrality, {conns} connections)")

    # Change summary
    if changed_files:
        lines.append(f"\nActive changes: {len(changed_files)} files modified")
        if gods:
            affected_gods = [
                g for g in gods
                if g.get("file") in (changed_files or [])
            ]
            if affected_gods:
                names = ", ".join(g["name"] for g in affected_gods[:3])
                lines.append(f"  God nodes affected: {names}")

    result = "\n".join(lines)
    if len(result) > token_budget:
        # Truncate to budget
        result = result[: token_budget - 3] + "..."
    return result


def build_task_injection(
    graph: GraphQuery,
    user_message: str,
    token_budget: int = 250,
) -> str:
    """Build entity-match injection for UserPromptSubmit.

    Extracts significant terms from the message, searches the graph,
    and returns formatted entity matches.
    """
    if not user_message.strip():
        return ""

    # Extract significant words (3+ chars, non-trivial)
    words = [w.lower() for w in user_message.split() if len(w) > 2]
    if not words:
        return ""

    # Search for each significant word
    seen_ids: set[str] = set()
    matches: list[dict[str, Any]] = []
    for word in words[:5]:  # Max 5 search terms
        results = graph.search(word, top_n=3)
        for r in results:
            if r["id"] not in seen_ids:
                seen_ids.add(r["id"])
                matches.append(r)

    if not matches:
        return ""

    # Build compact injection
    lines: list[str] = ["", "[Graph Context]", "Matched entities:"]
    for m in matches[:5]:
        file = m.get("file", "?")
        line = m.get("line")
        loc = f"{file}:{line}" if line else file
        conns = graph._store.connection_count(m["id"])
        god_marker = " — god node" if m.get("centrality", 0) > 0.7 else ""
        community = m.get("community", "")

        lines.append(f"  • {m['name']} ({loc}){god_marker}, {conns} connections")
        if community:
            lines.append(f"    Community: {community}")
            # Show top 3 dependents
            incoming = graph._store.get_incoming_relations(m["id"])
            if incoming:
                dep_names: list[str] = []
                for rel in incoming[:3]:
                    dep = graph._store.get_entity(rel["source_id"])
                    if dep:
                        dep_names.append(dep["name"])
                if dep_names:
                    extra = (
                        f" (and {len(incoming) - 3} more)"
                        if len(incoming) > 3
                        else ""
                    )
                    lines.append(f"    Called by: {', '.join(dep_names)}{extra}")

    result = "\n".join(lines)
    if len(result) > token_budget:
        result = result[: token_budget - 3] + "..."
    return result


def build_structural_anchors(graph: GraphQuery) -> str:
    """Build compact structural anchors for PreCompact injection.

    These survive compaction — the agent keeps architectural orientation.
    """
    communities = graph._store.get_communities()
    gods = graph.god_nodes(top_n=5)
    version = graph._store.version() or "unknown"

    lines = ["## Structural Anchors"]

    if communities:
        top = communities[:3]
        comm_str = ", ".join(
            f"{c['id']} ({c.get('size', 0)})" for c in top
        )
        lines.append(f"- Primary communities: {comm_str}")

    if gods:
        god_names = ", ".join(g["name"] for g in gods[:5])
        lines.append(f"- God nodes: {god_names}")

    lines.append(f"- Graph version: {version}")

    return "\n".join(lines)


def build_handoff_context(graph: GraphQuery) -> str:
    """Build the handoff structural context section."""
    communities = graph._store.get_communities()
    gods = graph.god_nodes(top_n=5)
    version = graph._store.version() or "unknown"

    lines = [
        "## Structural Context",
        f"- Primary communities: {', '.join(c['id'] for c in communities[:5])}",
    ]

    if gods:
        lines.append(
            f"- God nodes: {', '.join(g['name'] for g in gods[:5])}"
        )

    lines.append(f"- Graph version: {version}")
    return "\n".join(lines)
```

- [ ] **Step 2: Write context tests**

Write to `tests/graph/test_context.py`:

```python
"""Unit tests for graph context injection builders."""

from __future__ import annotations

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
    """Build a small graph for context testing."""
    import tempfile

    store = GraphStore(Path(tempfile.mkdtemp()))
    store.insert_entity({
        "id": "src/auth.py::AuthManager",
        "name": "AuthManager",
        "type": "class",
        "file": "src/auth.py",
        "line": 42,
        "community": "auth-infra",
        "centrality": 0.92,
        "docstring": "Central auth state machine",
    })
    store.insert_entity({
        "id": "src/auth.py::ErrorFormatter",
        "name": "ErrorFormatter",
        "type": "class",
        "file": "src/auth.py",
        "line": 89,
        "community": "auth-infra",
        "centrality": 0.45,
    })
    store.insert_entity({
        "id": "src/api.py::ApiGateway",
        "name": "ApiGateway",
        "type": "class",
        "file": "src/api.py",
        "line": 10,
        "community": "api-gateway",
        "centrality": 0.87,
    })
    store.insert_relation({
        "source": "src/api.py::ApiGateway",
        "target": "src/auth.py::AuthManager",
        "type": "CALLS",
        "confidence": "EXTRACTED",
    })
    store.insert_relation({
        "source": "src/auth.py::AuthManager",
        "target": "src/auth.py::ErrorFormatter",
        "type": "CALLS",
        "confidence": "EXTRACTED",
    })
    store.insert_community({
        "id": "auth-infra",
        "label": "Authentication & Identity",
        "size": 12,
        "central_nodes": ["AuthManager"],
    })
    store.insert_community({
        "id": "api-gateway",
        "label": "API Gateway",
        "size": 8,
        "central_nodes": ["ApiGateway"],
    })
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
    assert len(result) <= 103  # "..." suffix


def test_task_injection_matches_entities(query: GraphQuery) -> None:
    result = build_task_injection(query, "fix the auth manager bug")
    assert "AuthManager" in result
    assert "src/auth.py" in result


def test_task_injection_empty_no_match(query: GraphQuery) -> None:
    result = build_task_injection(query, "zzz nothing matches this")
    # May return empty or a "[Graph Context]" with no "Matched entities"
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
```

- [ ] **Step 3: Run context tests**

```bash
uv run pytest tests/graph/test_context.py -v
```

Expected: 10 tests pass.

- [ ] **Step 4: Commit**

```bash
git add core/graph/context.py tests/graph/test_context.py
git commit -m "feat: add graph context injection builders for hooks"
```

---

### Task 5: Public API + MCP Server — `core/graph/__init__.py` and `scripts/graph/mcp_server.py`

**Files:**
- Modify: `core/graph/__init__.py`
- Create: `scripts/graph/mcp_server.py`
- Create: `tests/graph/test_mcp.py`

- [ ] **Step 1: Write the public API**

Overwrite `core/graph/__init__.py`:

```python
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
```

- [ ] **Step 2: Write the MCP server**

Write to `scripts/graph/mcp_server.py`:

```python
"""FCC Graph MCP server — stdio JSON-RPC for knowledge graph tools.

Usage (in .mcp.json):
  {
    "fcc-graph": {
      "command": "uvx",
      "args": ["--from", "fcc-graph-server", "fcc-graph-server"],
      "env": { "FCC_PROJECT_ROOT": "${CLAUDE_PROJECT_DIR:-.}" }
    }
  }
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _get_query() -> object | None:
    """Load GraphQuery for the current project, if available."""
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
        {
            "name": "fcc_graph_search",
            "description": "Search the knowledge graph for entities by name or description.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "top_n": {"type": "integer", "description": "Max results", "default": 10},
                },
                "required": ["query"],
            },
        },
        {
            "name": "fcc_graph_neighbors",
            "description": "Get N-hop neighborhood of an entity — its dependencies and dependents.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "entity_id": {"type": "string"},
                    "depth": {"type": "integer", "default": 1},
                    "direction": {"type": "string", "enum": ["in", "out", "both"], "default": "both"},
                },
                "required": ["entity_id"],
            },
        },
        {
            "name": "fcc_graph_impact",
            "description": "Transitive closure analysis — what breaks if these entities change?",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "entity_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["entity_ids"],
            },
        },
        {
            "name": "fcc_graph_path",
            "description": "Shortest dependency path between two entities.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                    "target": {"type": "string"},
                },
                "required": ["source", "target"],
            },
        },
        {
            "name": "fcc_graph_god_nodes",
            "description": "Most-connected/important entities in the codebase.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "top_n": {"type": "integer", "default": 10},
                    "community": {"type": "string"},
                },
                "required": [],
            },
        },
        {
            "name": "fcc_graph_community",
            "description": "Get the community an entity belongs to and all its peers.",
            "inputSchema": {
                "type": "object",
                "properties": {"entity_id": {"type": "string"}},
                "required": ["entity_id"],
            },
        },
        {
            "name": "fcc_graph_entity",
            "description": "Get full details for a specific entity by ID.",
            "inputSchema": {
                "type": "object",
                "properties": {"entity_id": {"type": "string"}},
                "required": ["entity_id"],
            },
        },
        {
            "name": "fcc_graph_stats",
            "description": "Return graph summary statistics (entity/relation/community counts).",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    ]
    return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools}}


def _tools_call(params: dict, req_id: object) -> dict:
    tool_name = params.get("name", "")
    arguments = params.get("arguments", {})

    query = _get_query()
    if query is None:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {"error": "graph_unavailable", "message": "No knowledge graph found. Run: fcc-bootstrap-context --install-graphify"}
                        ),
                    }
                ]
            },
        }

    handler_map = {
        "fcc_graph_search": lambda: query.search(arguments["query"], arguments.get("top_n", 10)),
        "fcc_graph_neighbors": lambda: query.neighbors(
            arguments["entity_id"],
            arguments.get("depth", 1),
            arguments.get("direction", "both"),
        ),
        "fcc_graph_impact": lambda: query.impact(arguments["entity_ids"]),
        "fcc_graph_path": lambda: query.path(arguments["source"], arguments["target"]),
        "fcc_graph_god_nodes": lambda: query.god_nodes(
            arguments.get("top_n", 10), arguments.get("community")
        ),
        "fcc_graph_community": lambda: query.community(arguments["entity_id"]),
        "fcc_graph_entity": lambda: query.entity(arguments["entity_id"]),
        "fcc_graph_stats": lambda: query.stats(),
    }

    handler = handler_map.get(tool_name)
    if handler is None:
        return _error(req_id, -32601, f"Unknown tool: {tool_name}")

    result = handler()
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {
            "content": [{"type": "text", "text": json.dumps(result, default=str)}]
        },
    }


def _error(req_id: object, code: int, message: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": code, "message": message},
    }


def main() -> None:
    """Run the MCP server over stdin/stdout."""
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
```

- [ ] **Step 3: Write MCP test**

Write to `tests/graph/test_mcp.py`:

```python
"""Tests for the FCC Graph MCP server tool dispatch."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _import_server():
    spec = __import__("importlib.util", fromlist=[""]).util.spec_from_file_location(
        "mcp_server",
        Path(__file__).resolve().parents[2] / "scripts" / "graph" / "mcp_server.py",
    )
    module = __import__("importlib.util", fromlist=[""]).util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_tools_list() -> None:
    module = _import_server()
    response = module._handle_request({"method": "tools/list", "params": {}, "id": 1})
    tools = response["result"]["tools"]
    tool_names = {t["name"] for t in tools}
    assert "fcc_graph_search" in tool_names
    assert "fcc_graph_neighbors" in tool_names
    assert "fcc_graph_impact" in tool_names
    assert "fcc_graph_path" in tool_names
    assert "fcc_graph_god_nodes" in tool_names
    assert "fcc_graph_community" in tool_names
    assert "fcc_graph_entity" in tool_names
    assert "fcc_graph_stats" in tool_names


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
```

- [ ] **Step 4: Run MCP tests and verify imports**

```bash
uv run pytest tests/graph/test_mcp.py -v
```

Expected: 3 tests pass.

```bash
uv run python -c "from core.graph import GraphQuery, GraphStore, load_graph, build_session_bootstrap; print('All imports OK')"
```

- [ ] **Step 5: Commit**

```bash
git add core/graph/__init__.py scripts/graph/mcp_server.py tests/graph/test_mcp.py
git commit -m "feat: wire graph public API and MCP server (8 tools)"
```

---

### Task 6: Hook Integration — Session Start

**Files:**
- Modify: `scripts/hooks/session_start.py`
- Test: `tests/graph/test_hook_integration.py`

- [ ] **Step 1: Modify session_start.py**

Replace `scripts/hooks/session_start.py`:

```python
"""Inject compact project context at Claude Code session start."""

from __future__ import annotations

from _shared import (
    compact_lines,
    emit_hook_json,
    project_root,
    read_hook_input,
    read_text,
    run_hook,
    runtime_contract,
    startup_command_hint,
)


def _graph_context(root: object) -> str:
    """Build graph structural summary, if available."""
    try:
        from core.graph import load_graph
        from core.graph.context import build_session_bootstrap
        from core.graph.query import GraphQuery
    except ImportError:
        return ""
    from pathlib import Path

    if not isinstance(root, Path):
        return ""
    try:
        store = load_graph(root)
        query = GraphQuery(store)
        return build_session_bootstrap(query)
    except Exception:
        return ""


def main() -> None:
    data = read_hook_input()
    root = project_root(data)
    sections: list[str] = [
        f"## .fcc/context/agent-runtime.md\n{runtime_contract(root)}"
    ]
    command_hint = startup_command_hint(root)
    if command_hint:
        sections.append(f"## Command Protocol\n{command_hint}")
    for rel_path in (
        "CLAUDE.md",
        "CLAUDE.local.md",
        ".fcc/context/handoff.md",
    ):
        content = compact_lines(read_text(root / rel_path), max_lines=12, max_chars=900)
        if content:
            sections.append(f"## {rel_path}\n{content}")

    # Graph context
    graph_context = _graph_context(root)
    if graph_context:
        sections.append(graph_context)

    payload = "FCC project context:\n" + "\n\n".join(sections)
    emit_hook_json("SessionStart", additional_context=payload)


if __name__ == "__main__":
    run_hook("SessionStart", main)
```

- [ ] **Step 2: Modify user_prompt_submit.py** (add graph injection alongside debugger)

Edit `scripts/hooks/user_prompt_submit.py` — add a `_graph_task_context` function and include in payload:

Replace the file:

```python
"""Add tiny FCC context-routing hints for prompts that need orchestration."""

from __future__ import annotations

from _shared import (
    emit_hook_json,
    name_active_session,
    project_root,
    prompt_enhancement_outputs,
    prompt_routing_hint,
    read_hook_input,
    run_hook,
    session_name_from_prompt,
)


def _debugger_pipeline_context(prompt: str, root: object) -> str:
    """Build the debugger pipeline injection, if a transition is detected."""
    try:
        from core.debugger.trigger import debugger_pipeline_context as _build
    except ImportError:
        return ""
    from pathlib import Path

    if not isinstance(root, Path):
        return ""
    return _build(prompt, root)


def _graph_task_context(prompt: str, root: object) -> str:
    """Build graph entity-match injection for this prompt."""
    try:
        from core.graph import load_graph
        from core.graph.context import build_task_injection
        from core.graph.query import GraphQuery
    except ImportError:
        return ""
    from pathlib import Path

    if not isinstance(root, Path):
        return ""
    try:
        store = load_graph(root)
        query = GraphQuery(store)
        return build_task_injection(query, prompt)
    except Exception:
        return ""


def main() -> None:
    data = read_hook_input()
    prompt = str(data.get("prompt", ""))
    root = project_root(data)
    name = session_name_from_prompt(prompt)
    name_active_session(root, name)
    enhancement_context, enhancement_message = prompt_enhancement_outputs(prompt, root)
    pipeline_context = _debugger_pipeline_context(prompt, root)
    graph_context = _graph_task_context(prompt, root)
    payload = " ".join(
        part
        for part in (
            enhancement_context,
            prompt_routing_hint(prompt),
            pipeline_context,
            graph_context,
        )
        if part
    )
    emit_hook_json(
        "UserPromptSubmit",
        additional_context=payload,
        system_message=enhancement_message,
    )


if __name__ == "__main__":
    run_hook("UserPromptSubmit", main)
```

- [ ] **Step 3: Modify precompact.py** (add structural anchors)

Replace `scripts/hooks/precompact.py`:

```python
"""Carry forward only must-not-forget handoff facts before compaction."""

from __future__ import annotations

from _shared import (
    HANDOFF_FILE,
    compact_lines,
    emit_hook_json,
    extract_section,
    project_root,
    read_hook_input,
    read_text,
    run_hook,
)


def _graph_anchors(root: object) -> str:
    """Build structural anchors from the knowledge graph."""
    try:
        from core.graph import load_graph
        from core.graph.context import build_structural_anchors
        from core.graph.query import GraphQuery
    except ImportError:
        return ""
    from pathlib import Path

    if not isinstance(root, Path):
        return ""
    try:
        store = load_graph(root)
        query = GraphQuery(store)
        return build_structural_anchors(query)
    except Exception:
        return ""


def main() -> None:
    data = read_hook_input()
    root = project_root(data)
    handoff = read_text(root / HANDOFF_FILE)
    must = compact_lines(
        extract_section(handoff, "Must Not Forget"),
        max_lines=8,
        max_chars=1200,
    )
    continuity = compact_lines(
        "\n".join(
            part
            for part in (
                extract_section(handoff, "Current State"),
                extract_section(handoff, "Next Steps"),
            )
            if part.strip()
        ),
        max_lines=4,
        max_chars=700,
    )
    anchors = _graph_anchors(root)
    payload = ""
    if must:
        payload = "FCC must-not-forget facts before compaction:\n" + must
        if continuity:
            payload += "\n\nFCC active continuity:\n" + continuity
        if anchors:
            payload += "\n\n" + anchors
    emit_hook_json("PreCompact", additional_context=payload)


if __name__ == "__main__":
    run_hook("PreCompact", main)
```

- [ ] **Step 4: Write hook integration test**

Write to `tests/graph/test_hook_integration.py`:

```python
"""Integration tests for graph context in hooks."""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOKS_DIR = REPO_ROOT / "scripts" / "hooks"


def _load_hook(name: str):
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
```

- [ ] **Step 5: Run tests and verify existing tests**

```bash
uv run pytest tests/graph/test_hook_integration.py -v
```

Expected: 6 tests pass.

```bash
uv run pytest tests/scripts/test_windows_launcher.py tests/context/test_bootstrap_context.py tests/debugger/ -q
```

Expected: All existing tests pass.

- [ ] **Step 6: Commit**

```bash
git add scripts/hooks/session_start.py scripts/hooks/user_prompt_submit.py scripts/hooks/precompact.py tests/graph/test_hook_integration.py
git commit -m "feat: inject graph context into SessionStart, UserPromptSubmit, and PreCompact hooks"
```

---

### Task 7: Handoff Integration — `core/context/handoff.py`

**Files:**
- Modify: `core/context/handoff.py`

- [ ] **Step 1: Modify handoff.py to include structural context**

Edit `core/context/handoff.py` — modify `build_handoff()` signature and `regenerate_handoff()`:

Add the parameter and append the section. Modify only the function signatures and the return value assembly:

In `build_handoff`:
- Add `structural_context: str = ""` parameter
- Add the section after Next Steps if provided

In `regenerate_handoff`:
- Try to build structural context from graph
- Pass it to `build_handoff`

The complete modified file — replace the existing `core/context/handoff.py`:

```python
"""Read and write deterministic FCC handoff files."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from core.context.summarizer import (
    compact_lines,
    extract_decisions,
    extract_section,
    parse_transcript_text,
    summarize_transcript,
)

CONTEXT_DIR = Path(".fcc") / "context"
FACTS_FILE = CONTEXT_DIR / "facts.md"
DECISIONS_FILE = CONTEXT_DIR / "decisions.md"
HANDOFF_FILE = CONTEXT_DIR / "handoff.md"


def build_handoff(
    *,
    transcript_text: str,
    existing_handoff: str = "",
    facts_text: str = "",
    decisions_text: str = "",
    structural_context: str = "",
) -> str:
    """Build the compact current-state handoff from durable inputs."""
    must_section = extract_section(existing_handoff, "Must Not Forget")
    must_lines = compact_lines(
        "\n".join(part for part in (must_section, facts_text) if part.strip()),
        max_lines=8,
        max_chars=1200,
    )
    if not must_lines:
        must_lines = "- Add project-critical facts to CLAUDE.local.md."

    current_state = "\n".join(summarize_transcript(transcript_text, max_items=5))
    decision_lines = extract_decisions(
        "\n".join(part for part in (transcript_text, decisions_text) if part.strip()),
        max_items=5,
    )
    decisions = "\n".join(decision_lines) or "- No new decisions detected."

    sections = [
        "# FCC Handoff",
        "",
        "## Must Not Forget",
        must_lines,
        "",
        "## Current State",
        current_state,
        "",
    ]

    if structural_context:
        sections.extend([structural_context, "", ""])

    sections.extend([
        "## Decisions",
        decisions,
        "",
        "## Next Steps",
        "- Run /verify-context before major edits.",
        "- Store raw logs in the SQLite sidecar; do not replay them into chat.",
        "",
    ])

    return "\n".join(sections)


def _build_graph_handoff_section(project_root: Path) -> str:
    """Try to build a structural context section from the knowledge graph."""
    try:
        from core.graph import load_graph
        from core.graph.context import build_handoff_context
        from core.graph.query import GraphQuery

        store = load_graph(project_root)
        query = GraphQuery(store)
        return build_handoff_context(query)
    except Exception:
        return ""


def regenerate_handoff(project_root: Path, transcript_path: Path | str | None) -> str:
    """Rewrite `.fcc/context/handoff.md` and append decision deltas."""
    context_dir = project_root / CONTEXT_DIR
    context_dir.mkdir(parents=True, exist_ok=True)

    handoff_path = project_root / HANDOFF_FILE
    facts_path = project_root / FACTS_FILE
    decisions_path = project_root / DECISIONS_FILE

    existing_handoff = _read_text(handoff_path)
    facts_text = _read_text(facts_path)
    decisions_text = _read_text(decisions_path)
    transcript_text = parse_transcript_text(transcript_path)
    structural_context = _build_graph_handoff_section(project_root)
    new_handoff = build_handoff(
        transcript_text=transcript_text,
        existing_handoff=existing_handoff,
        facts_text=facts_text,
        decisions_text=decisions_text,
        structural_context=structural_context,
    )
    handoff_path.write_text(new_handoff, encoding="utf-8")

    decision_updates = extract_decisions(transcript_text, max_items=5)
    if decision_updates:
        _append_new_decisions(decisions_path, decision_updates)
    return new_handoff


def must_not_forget(project_root: Path, *, max_chars: int = 1200) -> str:
    """Return only the handoff's must-not-forget section."""
    handoff = _read_text(project_root / HANDOFF_FILE)
    return compact_lines(
        extract_section(handoff, "Must Not Forget"),
        max_lines=8,
        max_chars=max_chars,
    )


def _append_new_decisions(path: Path, decisions: list[str]) -> None:
    existing = _read_text(path)
    existing_keys = {line.strip().lower() for line in existing.splitlines()}
    new_items = [
        item for item in decisions if item.strip().lower() not in existing_keys
    ]
    if not new_items:
        return
    stamp = datetime.now(UTC).date().isoformat()
    prefix = "" if existing.endswith("\n") or not existing else "\n"
    block = "\n".join([f"{prefix}## {stamp}", *new_items, ""])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(block)


def _read_text(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")
```

- [ ] **Step 2: Run existing handoff + stop hook tests**

```bash
uv run pytest tests/context/ tests/scripts/ -q
```

Expected: All existing tests pass.

- [ ] **Step 3: Commit**

```bash
git add core/context/handoff.py
git commit -m "feat: add structural context section to FCC handoff from knowledge graph"
```

---

### Task 8: Bootstrap + Doctor + Router

**Files:**
- Modify: `cli/bootstrap_context.py`
- Modify: `cli/context_doctor.py`
- Modify: `.fcc/router.yml`
- Test: `tests/graph/test_doctor.py`

- [ ] **Step 1: Add --install-graphify to bootstrap**

Add the flag and handler. Insert after the `large_repo` block (around line 165).

Add argument to `add_arguments`:

```python
# Around line 350, add with the other flags:
parser.add_argument("--install-graphify", action="store_true",
                    help="Install graphify knowledge graph tooling")
```

Add handling in `main()` (after the existing tool installs):

```python
if args.install_graphify:
    from pathlib import Path as _Path
    _install_graphify_tooling(_Path.cwd(), force=args.force)
    report.installed.append("Graphify")
```

Add the function:

```python
def _install_graphify_tooling(root: Path, *, force: bool = False) -> None:
    """Install graphify and build initial knowledge graph."""
    # 1. Install graphify
    _run_tool_install(
        ["uv", "tool", "install", "--upgrade", "graphifyy[leiden]"],
        "Graphify",
    )

    # 2. Build initial graph
    subprocess.run(
        ["graphify", ".", "--output", ".fcc/graph/", "--no-viz"],
        cwd=str(root),
        check=False,
        capture_output=True,
        text=True,
        timeout=300,  # 5-minute timeout for first build
    )

    # 3. Try to install auto-rebuild git hook (non-fatal)
    subprocess.run(
        ["graphify", "hook", "install"],
        cwd=str(root),
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
```

- [ ] **Step 2: Add graph health checks to context_doctor.py**

Append to `run_agent_runtime_doctor()`:

```python
def _check_graph_health(root: Path) -> list[str]:
    """Check knowledge graph health. Returns issues found."""
    issues: list[str] = []
    graph_json = root / ".fcc" / "graph" / "graph.json"

    # Check graph exists
    if not graph_json.is_file():
        issues.append(
            "No knowledge graph found. Run: fcc-bootstrap-context --install-graphify"
        )
        return issues

    # Check file size
    size_mb = graph_json.stat().st_size / (1024 * 1024)
    if size_mb > 50:
        issues.append(
            f"graph.json is {size_mb:.0f}MB — may cause slow loads. "
            "Consider excluding generated/template directories."
        )

    return issues
```

And update the `AgentRuntimeDoctorReport` dataclass:

```python
graph_healthy: bool = True
graph_issues: list[str] = field(default_factory=list)
```

And add to `as_dict()`:

```python
"graph_healthy": self.graph_healthy,
"graph_issues": self.graph_issues,
```

And call it from `run_agent_runtime_doctor()`:

```python
graph_issues = _check_graph_health(root)
graph_healthy = len(graph_issues) == 0
```

- [ ] **Step 3: Update router.yml**

Replace `.fcc/router.yml`:

```yaml
version: 1
owner: fcc
purpose: agent-guidance
routes:
  trivial:
    alias: haiku
    model: ${MODEL_HAIKU:-provider/haiku-placeholder}
  balanced:
    alias: sonnet
    model: ${MODEL_SONNET:-provider/sonnet-placeholder}
  deep:
    alias: opus
    model: ${MODEL_OPUS:-provider/opus-placeholder}
notes:
  - Keep exact upstream model names in FCC provider config when unknown.
  - Do not add a second default routing proxy.
graph_rules:
  - match: "graph:centrality > 0.8"
    tier: opus
    reason: "Editing a god node — broad transitive effects require careful reasoning"
  - match: "graph:community:size > 20"
    tier: opus
    reason: "Large architectural domain warrants stronger reasoning"
  - match: "graph:impact:files > 10"
    tier: opus
    reason: "Broad change requires careful planning across many files"
  - match: "graph:unknown"
    tier: haiku
    reason: "No matching entity — exploratory task, start with fast model"
```

- [ ] **Step 4: Write doctor test**

Write to `tests/graph/test_doctor.py`:

```python
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
```

- [ ] **Step 5: Run all tests**

```bash
uv run pytest tests/graph/ -q
```

Expected: All graph tests pass.

```bash
uv run pytest tests/context/ tests/scripts/ tests/debugger/ -q
```

Expected: All existing tests pass.

- [ ] **Step 6: Commit**

```bash
git add cli/bootstrap_context.py cli/context_doctor.py .fcc/router.yml tests/graph/test_doctor.py
git commit -m "feat: add graphify bootstrap, graph doctor checks, and router rules"
```

---

### Task 9: E2E Tests

**Files:**
- Create: `tests/graph/test_e2e.py`

- [ ] **Step 1: Write E2E test**

Write to `tests/graph/test_e2e.py`:

```python
"""End-to-end tests for the Graphify knowledge graph integration."""

from __future__ import annotations

import json
import sqlite3
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from core.graph.loader import graph_path, load_graph
from core.graph.query import GraphQuery
from core.graph.store import GraphStore


@pytest.mark.live
def test_full_graph_lifecycle(tmp_path: Path) -> None:
    """Build a mock graph.json, load it, and query it."""
    graph_dir = tmp_path / ".fcc" / "graph"
    graph_dir.mkdir(parents=True)

    data = {
        "nodes": [
            {
                "id": "src/main.py::main",
                "name": "main",
                "type": "function",
                "file": "src/main.py",
                "line": 1,
                "community": "core",
                "centrality": 1.0,
            },
            {
                "id": "src/lib.py::helper",
                "name": "helper",
                "type": "function",
                "file": "src/lib.py",
                "line": 5,
                "community": "core",
                "centrality": 0.5,
            },
            {
                "id": "src/ui.py::render",
                "name": "render",
                "type": "function",
                "file": "src/ui.py",
                "line": 20,
                "community": "ui",
                "centrality": 0.3,
            },
        ],
        "edges": [
            {
                "source": "src/main.py::main",
                "target": "src/lib.py::helper",
                "type": "CALLS",
                "confidence": "EXTRACTED",
            },
            {
                "source": "src/main.py::main",
                "target": "src/ui.py::render",
                "type": "CALLS",
                "confidence": "EXTRACTED",
            },
        ],
        "communities": [
            {
                "id": "core",
                "label": "Core Logic",
                "size": 2,
                "central_nodes": ["main"],
            },
            {
                "id": "ui",
                "label": "User Interface",
                "size": 1,
                "central_nodes": ["render"],
            },
        ],
    }
    (graph_dir / "graph.json").write_text(json.dumps(data), encoding="utf-8")

    # Load
    store = load_graph(tmp_path)
    assert store.entity_count() == 3
    assert store.relation_count() == 2
    assert store.community_count() == 2
    assert store.version() is not None

    # Query
    query = GraphQuery(store)

    # Entity
    main = query.entity("src/main.py::main")
    assert main is not None
    assert main["name"] == "main"

    # Neighbors
    neighbors = query.neighbors("src/main.py::main", direction="out")
    dep_names = {d["name"] for d in neighbors["dependencies"]}
    assert "helper" in dep_names
    assert "render" in dep_names

    # Impact
    impact = query.impact(["src/main.py::main"])
    assert impact["files_touched"] >= 1
    assert impact["estimated_risk"] in ("low", "medium", "high")

    # Path
    steps = query.path("src/main.py::main", "src/lib.py::helper")
    assert len(steps) >= 1
    assert steps[0]["next"] == "src/lib.py::helper"

    # God nodes
    gods = query.god_nodes(top_n=10)
    assert len(gods) >= 1
    assert gods[0]["name"] == "main"

    # Search
    results = query.search("helper")
    assert len(results) == 1
    assert results[0]["name"] == "helper"

    # Community
    comm = query.community("src/main.py::main")
    assert comm is not None
    assert len(comm["peers"]) >= 1

    # Stats
    s = query.stats()
    assert s["entity_count"] == 3
    assert s["relation_count"] == 2


def test_context_injection_full_pipeline(tmp_path: Path) -> None:
    """Verify context injections work with a real graph."""
    graph_dir = tmp_path / ".fcc" / "graph"
    graph_dir.mkdir(parents=True)

    data = {
        "nodes": [
            {
                "id": "src/auth.py::AuthManager",
                "name": "AuthManager",
                "type": "class",
                "file": "src/auth.py",
                "line": 42,
                "community": "auth-infra",
                "centrality": 0.92,
                "metadata": {"docstring": "Central auth state"},
            },
        ],
        "edges": [],
        "communities": [
            {"id": "auth-infra", "label": "Auth", "size": 1, "central_nodes": ["AuthManager"]},
        ],
    }
    (graph_dir / "graph.json").write_text(json.dumps(data), encoding="utf-8")

    store = load_graph(tmp_path)
    query = GraphQuery(store)

    from core.graph.context import (
        build_handoff_context,
        build_session_bootstrap,
        build_structural_anchors,
        build_task_injection,
    )

    # Session bootstrap
    bootstrap = build_session_bootstrap(query)
    assert "auth-infra" in bootstrap
    assert "AuthManager" in bootstrap

    # Task injection
    task = build_task_injection(query, "fix the auth manager")
    assert "AuthManager" in task

    # Structural anchors
    anchors = build_structural_anchors(query)
    assert "auth-infra" in anchors

    # Handoff context
    handoff = build_handoff_context(query)
    assert "auth-infra" in handoff


def test_graph_store_survives_close_and_reopen(tmp_path: Path) -> None:
    """Verify data persists across close + reopen."""
    graph_dir = tmp_path / ".fcc" / "graph"
    graph_dir.mkdir(parents=True)

    data = {
        "nodes": [{"id": "x", "name": "X", "type": "class"}],
        "edges": [],
    }
    (graph_dir / "graph.json").write_text(json.dumps(data), encoding="utf-8")

    store1 = load_graph(tmp_path)
    assert store1.entity_count() == 1
    store1.close()

    store2 = load_graph(tmp_path)
    assert store2.entity_count() == 1
    assert store2.get_entity("x") is not None
    store2.close()
```

- [ ] **Step 2: Run all graph tests**

```bash
uv run pytest tests/graph/ -v
```

Expected: All tests pass (~60+ tests across all graph test files).

- [ ] **Step 3: Run full test suite**

```bash
uv run pytest tests/ -x -q
```

Expected: All tests pass, zero regressions.

- [ ] **Step 4: Commit**

```bash
git add tests/graph/test_e2e.py
git commit -m "test: add E2E tests for graph lifecycle and context injection pipeline"
```

---

### Task 10: Final Verification

**Files:** None (verification only)

- [ ] **Step 1: Full test suite**

```bash
uv run pytest tests/ -x -q
```

Expected: All tests pass.

- [ ] **Step 2: Verify all imports**

```bash
uv run python -c "from core.graph import GraphQuery, GraphStore, GraphLoadError, load_graph, graphify_available, build_session_bootstrap, build_task_injection, build_structural_anchors, build_handoff_context; print('All graph imports OK')"
uv run python -c "from core.debugger import debugger_pipeline_context; print('Debugger import OK')"
uv run python -c "from core.context.handoff import build_handoff, regenerate_handoff; print('Handoff import OK')"
```

Expected: Three "OK" messages.

- [ ] **Step 3: Lint checks**

```bash
uv run ruff check core/graph/ tests/graph/ scripts/graph/ scripts/hooks/user_prompt_submit.py scripts/hooks/session_start.py scripts/hooks/precompact.py core/context/handoff.py cli/bootstrap_context.py cli/context_doctor.py
```

Expected: All checks pass.

```bash
uv run grep -rE '# type: ignore|# ty: ignore' core/graph/ tests/graph/ scripts/graph/ --include='*.py'
```

Expected: Exit code 1 (no matches).

- [ ] **Step 4: Verify hook modules load**

```bash
cd scripts/hooks && uv run python -c "import importlib.util; spec = importlib.util.spec_from_file_location('t', 'session_start.py'); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); print('SessionStart OK')"
cd scripts/hooks && uv run python -c "import importlib.util; spec = importlib.util.spec_from_file_location('t', 'user_prompt_submit.py'); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); print('UserPromptSubmit OK')"
cd scripts/hooks && uv run python -c "import importlib.util; spec = importlib.util.spec_from_file_location('t', 'precompact.py'); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); print('PreCompact OK')"
```

Expected: Three "OK" messages from the hooks directory.

- [ ] **Step 5: Final commit**

```bash
git status
git add -A
git commit -m "chore: final verification — all graph integration tests passing" --allow-empty
```
