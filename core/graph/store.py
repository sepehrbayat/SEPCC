"""SQLite-backed knowledge graph persistence for FCC Graphify integration."""

from __future__ import annotations

import contextlib
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
        self._closed = False
        self._sql_errors: list[str] = []  # B12: surfaced errors from row parsing
        self._fts_trigger_error: str | None = None
        self._create_tables()
        self._has_fts5 = self._check_fts5()

    def __enter__(self) -> GraphStore:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

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
                in_degree INTEGER DEFAULT 0,
                out_degree INTEGER DEFAULT 0,
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
        # Backfill columns for stores created before in_degree/out_degree existed.
        # Only swallow "duplicate column name" errors — re-raise all others.
        for col in ("in_degree", "out_degree"):
            try:
                self._conn.execute(
                    f"ALTER TABLE entities ADD COLUMN {col} INTEGER DEFAULT 0"
                )
            except sqlite3.OperationalError as exc:
                if "duplicate column" not in str(exc).lower():
                    raise
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_entities_file ON entities(file)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_entities_community ON entities(community)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_relations_source ON relations(source_id)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_relations_target ON relations(target_id)"
        )
        self._conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_relations_unique_edge
            ON relations(source_id, target_id, type)
            """
        )
        self._conn.commit()

    def _check_fts5(self) -> bool:
        """Create FTS5 virtual table and sync triggers.

        Returns True when FTS5 is available.  The virtual-table creation and
        trigger creation are tried separately so a trigger failure does not
        silently mask FTS5 availability.
        """
        # 1. Virtual table (FTS5 extension check)
        try:
            self._conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS entity_fts USING fts5(
                    name, docstring, intents,
                    content='entities', content_rowid='rowid'
                )
                """
            )
        except sqlite3.OperationalError:
            return False  # FTS5 extension not available at all

        # 2. Sync triggers (may fail on exotic SQLite builds)
        try:
            self._conn.executescript(
                """
                CREATE TRIGGER IF NOT EXISTS entities_ai AFTER INSERT ON entities BEGIN
                    INSERT INTO entity_fts(rowid, name, docstring, intents)
                    VALUES (new.rowid, new.name, new.docstring, new.intents);
                END;
                CREATE TRIGGER IF NOT EXISTS entities_ad AFTER DELETE ON entities BEGIN
                    INSERT INTO entity_fts(entity_fts, rowid, name, docstring, intents)
                    VALUES ('delete', old.rowid, old.name, old.docstring, old.intents);
                END;
                CREATE TRIGGER IF NOT EXISTS entities_au AFTER UPDATE ON entities BEGIN
                    INSERT INTO entity_fts(entity_fts, rowid, name, docstring, intents)
                    VALUES ('delete', old.rowid, old.name, old.docstring, old.intents);
                    INSERT INTO entity_fts(rowid, name, docstring, intents)
                    VALUES (new.rowid, new.name, new.docstring, new.intents);
                END;
                """
            )
        except sqlite3.OperationalError:
            self._fts_trigger_error = "FTS5 triggers could not be created"

        self._conn.commit()
        return True

    def insert_entity(self, entity: dict[str, Any]) -> None:
        eid = entity.get("id")
        if not eid or not isinstance(eid, str) or not eid.strip():
            return  # Silently skip entities without valid IDs
        self._conn.execute(
            """
            INSERT OR REPLACE INTO entities
            (id, name, type, file, line, community, centrality,
             docstring, intents, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                eid,
                entity.get("name", ""),
                entity.get("type", "unknown"),
                entity.get("file"),
                entity.get("line"),
                entity.get("community"),
                entity.get("centrality"),
                entity.get("docstring"),
                json.dumps(entity.get("intents", [])) if entity.get("intents") is not None else None,
                json.dumps(entity.get("metadata")) if entity.get("metadata") is not None else None,
            ),
        )

    def insert_relation(self, rel: dict[str, Any]) -> None:
        self._conn.execute(
            """
            INSERT OR IGNORE INTO relations (source_id, target_id, type, confidence, metadata)
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
        self._conn.execute("DELETE FROM relations")
        self._conn.execute("DELETE FROM entities")
        self._conn.execute("DELETE FROM communities")
        if self._has_fts5:
            with contextlib.suppress(sqlite3.OperationalError):
                self._conn.execute(
                    "INSERT INTO entity_fts(entity_fts) VALUES ('rebuild')"
                )
        self._conn.commit()

    def commit(self) -> None:
        self._conn.commit()

    def version(self) -> str | None:
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

    def meta_get(self, key: str) -> str | None:
        """Read an arbitrary value from schema_meta."""
        try:
            row = self._conn.execute(
                "SELECT value FROM schema_meta WHERE key = ?", (key,)
            ).fetchone()
            return row["value"] if row else None
        except sqlite3.OperationalError:
            return None

    def meta_set(self, key: str, value: str) -> None:
        """Write an arbitrary key-value pair to schema_meta."""
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_meta (
                key TEXT PRIMARY KEY, value TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            INSERT INTO schema_meta(key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )
        self._conn.commit()

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

    def get_community(self, community_id: str) -> dict[str, Any] | None:
        """Return a single community by ID, or None."""
        row = self._conn.execute(
            "SELECT * FROM communities WHERE id = ?", (community_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

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
        """Full-text search with progressive fallbacks for recall.

        Tries, in order: FTS5 → LIKE substring → token-AND → token-OR.
        At each step, if only rationale/doc entities are found, continues
        to the next fallback to find real code entities as well.
        """
        results: list[dict[str, Any]] = []
        seen_ids: set[str] = set()

        def _add(row_list):
            nonlocal seen_ids
            for r in row_list:
                eid = r["id"] if isinstance(r, dict) else r[0]
                if eid not in seen_ids:
                    seen_ids.add(eid)
                    results.append(self._row_to_dict(r) if hasattr(r, "keys") else r)

        def _code_count(rows):
            return sum(
                1 for r in rows
                if (r["type"] if isinstance(r, dict) else getattr(r, "type", "rationale")) == "code"
            )

        def _have_code():
            return sum(1 for r in results if r.get("type") == "code") > 0

        # 1. FTS5
        if self._has_fts5:
            escaped = _escape_fts5_query(query)
            try:
                rows = self._conn.execute(
                    """SELECT e.* FROM entities e
                       JOIN entity_fts fts ON e.rowid = fts.rowid
                       WHERE entity_fts MATCH ?
                       ORDER BY rank LIMIT ?""",
                    (escaped, limit),
                ).fetchall()
                _add(rows)
            except sqlite3.OperationalError:
                pass

        # 2. LIKE substring (always run if FTS5 didn't find code entities)
        if not _have_code():
            pattern = f"%{query}%"
            rows = self._conn.execute(
                """SELECT * FROM entities
                   WHERE name LIKE ? OR docstring LIKE ?
                   ORDER BY CASE WHEN name LIKE ? THEN 0 ELSE 1 END
                   LIMIT ?""",
                (pattern, pattern, pattern, limit),
            ).fetchall()
            _add(rows)

        # 3. Token-level fallbacks for naming convention mismatches
        tokens = [t.lower() for t in query.replace("_", " ").split() if len(t) > 1]
        if len(tokens) > 1 and not _have_code():
            # AND-fallback: all tokens must appear
            rows = self._conn.execute(
                """SELECT * FROM entities
                   WHERE {conditions}
                   ORDER BY name LIKE ? DESC
                   LIMIT ?""".format(
                    conditions=" AND ".join(
                        "(LOWER(name) LIKE ? OR LOWER(docstring) LIKE ?)"
                        for _ in tokens
                    )
                ),
                [
                    p for t in tokens for p in (f"%{t}%", f"%{t}%")
                ] + [f"%{query}%", limit],
            ).fetchall()
            _add(rows)

            # OR-fallback: match ANY token, ranked by match count
            if not _have_code():
                rows = self._conn.execute(
                    """SELECT * FROM entities
                       WHERE {conditions}
                       ORDER BY ({score}) DESC
                       LIMIT ?""".format(
                        conditions=" OR ".join(
                            "(LOWER(name) LIKE ? OR LOWER(docstring) LIKE ?)"
                            for _ in tokens
                        ),
                        score=" + ".join(
                            "(CASE WHEN LOWER(name) LIKE ? OR LOWER(docstring) LIKE ? THEN 1 ELSE 0 END)"
                            for _ in tokens
                        ),
                    ),
                    [
                        p for t in tokens for p in (f"%{t}%", f"%{t}%")
                    ] + [
                        p for t in tokens for p in (f"%{t}%", f"%{t}%")
                    ] + [limit],
                ).fetchall()
                _add(rows)

        return results[:limit]

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
        if self._closed:
            return
        self._closed = True
        self._conn.close()

    def warnings(self) -> list[str]:
        """Return accumulated non-fatal errors (JSON parse, FTS5 triggers, etc.)."""
        w: list[str] = list(self._sql_errors)
        if self._fts_trigger_error:
            w.append(self._fts_trigger_error)
        return w

    def _row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        for field in ("intents", "metadata", "central_nodes"):
            if field in d and isinstance(d[field], str):
                try:
                    d[field] = json.loads(d[field])
                except (json.JSONDecodeError, TypeError):
                    # Keep the raw string; accumulate the error so callers
                    # can detect corruption without crashing.
                    key = f"{field}:{d.get('id', '?')}"
                    self._sql_errors.append(key)
        return d


# ── FTS5 query escaping ────────────────────────────────────────────────

_FTS5_ESCAPE_CHARS = str.maketrans({
    '"': '""',
    '*': ' ',
    '^': ' ',
    '(': ' ',
    ')': ' ',
    '~': ' ',
    '\x00': ' ',
})


def _escape_fts5_query(query: str) -> str:
    """Sanitise a user-provided search string for safe FTS5 MATCH usage.

    Escapes the double-quote character (FTS5 phrase delimiter) and
    replaces other FTS5 syntax characters (``*``, ``^``, ``(``, ``)``,
    ``~``, null bytes) with spaces so they are treated as literal word
    boundaries rather than operators.
    """
    if not query:
        return '""'
    return query.translate(_FTS5_ESCAPE_CHARS)
