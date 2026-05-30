"""Store large terminal/tool outputs in FCC's SQLite context sidecar."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from core.context.sqlite_store import DEFAULT_INDEX_PATH, SQLiteContextStore


def store_context_output(
    content: str,
    *,
    kind: str,
    source: str,
    db_path: Path | str = DEFAULT_INDEX_PATH,
    handle: str | None = None,
) -> dict[str, str | int]:
    """Store output and return a JSON-serializable handle summary."""
    store = SQLiteContextStore(db_path)
    output_handle = store.store_output(
        content,
        kind=kind,
        source=source,
        handle=handle,
    )
    return {
        "handle": output_handle,
        "kind": kind,
        "source": source,
        "chars": len(content),
    }


def main(argv: Sequence[str] | None = None) -> None:
    """CLI entry point for storing tool or terminal output by handle."""
    parser = argparse.ArgumentParser(
        description="Store large output in FCC's SQLite FTS sidecar.",
    )
    parser.add_argument(
        "--file",
        type=Path,
        help="Read content from a file. Defaults to stdin.",
    )
    parser.add_argument(
        "--db",
        default=str(DEFAULT_INDEX_PATH),
        help="Path to the context SQLite database.",
    )
    parser.add_argument(
        "--kind",
        default="terminal",
        help="Output kind, such as terminal, tool, trace, or log.",
    )
    parser.add_argument(
        "--source",
        default="manual",
        help="Source command or tool name.",
    )
    parser.add_argument(
        "--handle",
        help="Optional explicit handle to replace/update.",
    )
    args = parser.parse_args(argv)

    if args.file is None:
        content = sys.stdin.read()
    else:
        content = args.file.read_text(encoding="utf-8", errors="replace")

    print(
        json.dumps(
            store_context_output(
                content,
                kind=args.kind,
                source=args.source,
                db_path=args.db,
                handle=args.handle,
            )
        )
    )


if __name__ == "__main__":
    main()
