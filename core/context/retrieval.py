"""Query helpers and CLI for FCC's SQLite context sidecar."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from core.context.sqlite_store import DEFAULT_INDEX_PATH, SQLiteContextStore


def query_index(
    query: str,
    *,
    db_path: Path | str = DEFAULT_INDEX_PATH,
    limit: int = 5,
) -> list[dict[str, str | float]]:
    """Return JSON-serializable search results for indexed outputs."""
    store = SQLiteContextStore(db_path)
    return [
        {
            "handle": result.handle,
            "kind": result.kind,
            "source": result.source,
            "score": result.score,
            "snippet": result.snippet,
        }
        for result in store.search(query, limit=limit)
    ]


def main(argv: Sequence[str] | None = None) -> None:
    """CLI entry point for querying indexed tool output handles."""
    parser = argparse.ArgumentParser(
        description="Query FCC's SQLite FTS sidecar for stored tool outputs.",
    )
    parser.add_argument("query", help="Search terms to match with SQLite FTS5.")
    parser.add_argument(
        "--db",
        default=str(DEFAULT_INDEX_PATH),
        help="Path to the context SQLite database.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Maximum number of matches to return.",
    )
    args = parser.parse_args(argv)
    print(json.dumps(query_index(args.query, db_path=args.db, limit=args.limit)))


if __name__ == "__main__":
    main()
