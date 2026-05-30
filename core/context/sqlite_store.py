"""SQLite FTS5 sidecar for compact retrieval of large tool outputs."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_INDEX_PATH = Path(".fcc") / "indexes" / "context.sqlite"

_FTS_TOKEN_RE = re.compile(r"[\w./:-]+", re.ASCII)


@dataclass(frozen=True)
class SearchResult:
    """One indexed output match."""

    handle: str
    kind: str
    source: str
    score: float
    snippet: str


def make_match_query(query: str) -> str:
    """Return a conservative FTS5 MATCH query built from user text."""
    tokens = [token for token in _FTS_TOKEN_RE.findall(query) if token.strip()]
    if not tokens:
        return ""
    return " OR ".join(f'"{token}"' for token in tokens[:16])


class SQLiteContextStore:
    """Persist and query large terminal/tool outputs by compact handles."""

    def __init__(self, db_path: Path | str = DEFAULT_INDEX_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def store_output(
        self,
        content: str,
        *,
        kind: str,
        source: str,
        handle: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Store large output text and return its stable retrieval handle."""
        clean_kind = kind.strip() or "tool-output"
        clean_source = source.strip() or "unknown"
        output_handle = handle or self._make_handle(clean_kind, clean_source, content)
        created_at = datetime.now(UTC).isoformat()
        metadata_json = json.dumps(metadata or {}, sort_keys=True)

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO outputs(handle, kind, source, content, created_at, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(handle) DO UPDATE SET
                    kind = excluded.kind,
                    source = excluded.source,
                    content = excluded.content,
                    created_at = excluded.created_at,
                    metadata_json = excluded.metadata_json
                """,
                (
                    output_handle,
                    clean_kind,
                    clean_source,
                    content,
                    created_at,
                    metadata_json,
                ),
            )
        return output_handle

    def get_output(self, handle: str) -> str | None:
        """Return raw stored output text for a handle."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT content FROM outputs WHERE handle = ?",
                (handle,),
            ).fetchone()
        if row is None:
            return None
        return str(row["content"])

    def search(self, query: str, *, limit: int = 5) -> list[SearchResult]:
        """Search indexed outputs using FTS5 BM25 ranking."""
        match_query = make_match_query(query)
        if not match_query:
            return []

        with self._connect() as conn:
            try:
                rows = conn.execute(
                    """
                    SELECT
                        outputs.handle,
                        outputs.kind,
                        outputs.source,
                        bm25(outputs_fts) AS score,
                        snippet(outputs_fts, 3, '[', ']', '...', 12) AS snippet
                    FROM outputs_fts
                    JOIN outputs ON outputs.id = outputs_fts.rowid
                    WHERE outputs_fts MATCH ?
                    ORDER BY score
                    LIMIT ?
                    """,
                    (match_query, max(1, min(limit, 50))),
                ).fetchall()
            except sqlite3.OperationalError:
                return []

        return [
            SearchResult(
                handle=str(row["handle"]),
                kind=str(row["kind"]),
                source=str(row["source"]),
                score=float(row["score"]),
                snippet=str(row["snippet"]),
            )
            for row in rows
        ]

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS outputs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    handle TEXT NOT NULL UNIQUE,
                    kind TEXT NOT NULL,
                    source TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS outputs_fts USING fts5(
                    handle,
                    kind,
                    source,
                    content,
                    content='outputs',
                    content_rowid='id'
                );

                CREATE TRIGGER IF NOT EXISTS outputs_ai
                AFTER INSERT ON outputs
                BEGIN
                    INSERT INTO outputs_fts(rowid, handle, kind, source, content)
                    VALUES (new.id, new.handle, new.kind, new.source, new.content);
                END;

                CREATE TRIGGER IF NOT EXISTS outputs_ad
                AFTER DELETE ON outputs
                BEGIN
                    INSERT INTO outputs_fts(outputs_fts, rowid, handle, kind, source, content)
                    VALUES ('delete', old.id, old.handle, old.kind, old.source, old.content);
                END;

                CREATE TRIGGER IF NOT EXISTS outputs_au
                AFTER UPDATE ON outputs
                BEGIN
                    INSERT INTO outputs_fts(outputs_fts, rowid, handle, kind, source, content)
                    VALUES ('delete', old.id, old.handle, old.kind, old.source, old.content);
                    INSERT INTO outputs_fts(rowid, handle, kind, source, content)
                    VALUES (new.id, new.handle, new.kind, new.source, new.content);
                END;
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _make_handle(kind: str, source: str, content: str) -> str:
        digest = hashlib.sha256(f"{kind}\0{source}\0{content}".encode()).hexdigest()[
            :16
        ]
        normalized_kind = re.sub(r"[^a-zA-Z0-9_-]+", "-", kind.lower()).strip("-")
        prefix = normalized_kind or "output"
        return f"{prefix}-{digest}"
