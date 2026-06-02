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
        self._conn.commit()

    def _check_fts5(self) -> bool:
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
                if rows:
                    return [self._row_to_dict(r) for r in rows]
            except sqlite3.OperationalError:
                pass
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
        for field in ("intents", "metadata", "central_nodes"):
            if field in d and isinstance(d[field], str):
                try:
                    d[field] = json.loads(d[field])
                except (json.JSONDecodeError, TypeError):
                    pass
        return d
