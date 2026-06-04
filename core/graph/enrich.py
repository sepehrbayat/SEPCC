"""Semantic enrichment — populate docstrings and signatures from source files.

After graphify's AST-only extraction yields structure with empty semantics,
this module reads each entity's source file and extracts:

- Docstrings (stored in ``entities.docstring``)
- Function/class signatures, kind, decorators, base classes
  (stored as JSON in ``entities.metadata``)

Files are parsed once and cached, since many entities share the same file.
"""
from __future__ import annotations

import ast
import json
import sqlite3
from pathlib import Path
from typing import Any


# ── Public API ──────────────────────────────────────────────────────────────

def enrich_store(root: Path, store: Any) -> int:
    """Populate docstrings and signatures for all code entities in the store.

    Returns the number of entities enriched.
    """
    conn = store._conn
    rows = conn.execute(
        """SELECT id, name, file, line FROM entities
           WHERE type = 'code' AND file IS NOT NULL AND file != ''
           ORDER BY file, line"""
    ).fetchall()

    if not rows:
        return 0

    parsed_cache: dict[str, ast.AST | None] = {}
    enriched = 0

    for row in rows:
        eid = row["id"]
        efile = row["file"]
        eline_raw = str(row["line"]).lstrip("L") if row["line"] else "0"
        try:
            eline = int(eline_raw)
        except (ValueError, TypeError):
            eline = 0

        if eline == 0 or not efile:
            continue

        # Parse file once, cache
        tree = parsed_cache.get(efile, _NOT_FOUND)
        if tree is _NOT_FOUND:
            full_path = root / efile
            if full_path.is_file():
                try:
                    tree = ast.parse(full_path.read_text(encoding="utf-8"))
                except (SyntaxError, UnicodeDecodeError, OSError):
                    tree = None
            else:
                tree = None
            parsed_cache[efile] = tree

        if tree is None:
            continue

        # Find the definition node near this line
        node = _find_node_at_line(tree, eline)
        if node is None:
            continue

        info = _extract_node_info(node)
        docstring = info.get("docstring", "")

        # Store docstring
        conn.execute(
            "UPDATE entities SET docstring = ? WHERE id = ?",
            (docstring, eid),
        )

        # Store metadata (signature, kind, decorators, bases)
        meta = {k: v for k, v in info.items() if k != "docstring" and v}
        if meta:
            conn.execute(
                "UPDATE entities SET metadata = ? WHERE id = ?",
                (json.dumps(meta, separators=(",", ":")), eid),
            )

        enriched += 1

    conn.commit()
    return enriched


# ── AST Helpers ─────────────────────────────────────────────────────────────

_NOT_FOUND = object()  # sentinel for parse cache


def _find_node_at_line(
    tree: ast.AST, line_num: int
) -> ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | None:
    """Find the definition node closest to *line_num*.

    Searches within a -10/+5 window around the target line.
    """
    best_node = None
    best_dist = 999

    for node in ast.walk(tree):
        node_line = getattr(node, "lineno", 0)
        if node_line == 0:
            continue
        dist = node_line - line_num
        if dist < -10 or dist > 5:
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if abs(dist) < best_dist:
                best_dist = abs(dist)
                best_node = node

    return best_node


def _extract_node_info(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
) -> dict[str, Any]:
    """Extract docstring, signature, kind, decorators, and bases from a node."""
    info: dict[str, Any] = {
        "docstring": ast.get_docstring(node) or "",
        "signature": "",
        "kind": type(node).__name__,
        "decorators": [],
        "bases": [],
    }

    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        info["kind"] = "function"
        if isinstance(node, ast.AsyncFunctionDef):
            prefix = "async "
        else:
            prefix = ""

        # Build signature
        arg_strs = []
        for arg in node.args.args:
            a = arg.arg
            if arg.annotation:
                a += f": {ast.unparse(arg.annotation)}"
            arg_strs.append(a)
        defaults = list(node.args.defaults)
        if defaults:
            offset = len(arg_strs) - len(defaults)
            for i, d in enumerate(defaults):
                arg_strs[offset + i] += f" = {ast.unparse(d)}"
        returns = ""
        if node.returns:
            returns = f" -> {ast.unparse(node.returns)}"
        info["signature"] = f"{prefix}def {node.name}({', '.join(arg_strs)}){returns}"

    elif isinstance(node, ast.ClassDef):
        info["kind"] = "class"
        info["signature"] = f"class {node.name}"
        info["bases"] = [ast.unparse(b) for b in node.bases]

    info["decorators"] = [ast.unparse(d) for d in node.decorator_list]

    return info
