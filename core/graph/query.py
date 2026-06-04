"""Graph traversal queries on the knowledge graph."""

from __future__ import annotations

import subprocess
from collections import deque
from typing import Any, Literal

from core.graph.store import GraphStore


# ── Test-file detection ────────────────────────────────────────────────

_TEST_PATH_SEGMENTS = frozenset({
    "/tests/", "/test/", "/smoke/", "/spec/",
    "test_", "conftest.py", "__pycache__",
})

_PYTHON_BUILTIN_NAMES = frozenset({
    "str", "int", "float", "bool", "bytes", "object", "type",
    "list", "dict", "set", "tuple", "frozenset", "None", "Any",
    "BaseException", "Exception", "ValueError", "TypeError",
    "RuntimeError", "OSError", "KeyError", "AttributeError",
    "NotImplementedError", "StopIteration", "GeneratorExit",
    "KeyboardInterrupt", "SystemExit", "MemoryError",
    "MagicMock", "Mock", "AsyncMock", "patch",
})


def _is_builtin_entity(entity: dict[str, Any]) -> bool:
    """Return True if an entity is a Python builtin / stdlib / external symbol.

    Entities without source files AND with generic names are likely graphify
    artifacts from type annotations and usage sites, not project code.
    """
    name = str(entity.get("name") or entity.get("id", ""))
    return name in _PYTHON_BUILTIN_NAMES


def _entity_type_ok(eid: str, store: GraphStore) -> bool:
    """Return False for entity types that should not appear in impact results.

    Rationale entities (``"type":"rationale"``) are docstring/comment excerpts
    graphify extracts.  They have no executable code and cannot "break" when a
    dependency changes.
    """
    entity = store.get_entity(eid)
    if entity is None:
        return True  # Missing entity is not rationale
    return entity.get("type") != "rationale"


def _is_test_entity(entity: dict[str, Any] | None) -> bool:
    """Return True if the entity lives under a test/smoke/spec directory."""
    if entity is None:
        return False
    file = entity.get("file") or entity.get("source_file") or ""
    if not file:
        return False
    file_lower = file.lower().replace("\\", "/")
    for seg in _TEST_PATH_SEGMENTS:
        if seg in file_lower:
            return True
    return False


def _split_by_test(
    entities: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split entities into (production, test) lists."""
    prod: list[dict[str, Any]] = []
    tests: list[dict[str, Any]] = []
    for e in entities:
        if _is_test_entity(e):
            tests.append(e)
        else:
            prod.append(e)
    return prod, tests


class GraphQuery:
    """Read-only graph traversal operations over a GraphStore."""

    def __init__(self, store: GraphStore) -> None:
        self._store = store

    def entity(self, entity_id: str) -> dict[str, Any] | None:
        return self._store.get_entity(entity_id)

    def neighbors(
        self,
        entity_id: str,
        depth: int = 1,
        direction: Literal["in", "out", "both"] = "both",
    ) -> dict[str, Any]:
        entity = self._store.get_entity(entity_id)
        if entity is None:
            return {"entity": None, "dependencies": [], "dependents": [], "community_peers": []}

        deps: list[dict[str, Any]] = []
        dents: list[dict[str, Any]] = []
        if direction in ("out", "both"):
            deps = self._bfs(entity_id, depth, "out")
        if direction in ("in", "both"):
            dents = self._bfs(entity_id, depth, "in")

        peers: list[dict[str, Any]] = []
        community = entity.get("community")
        if community:
            peers = [
                e for e in self._store.get_entities_by_community(community)
                if e["id"] != entity_id
            ]

        return {"entity": entity, "dependencies": deps, "dependents": dents, "community_peers": peers}

    def _bfs(self, start: str, max_depth: int, direction: str) -> list[dict[str, Any]]:
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

    def impact(
        self,
        entity_ids: list[str],
        relation_types: list[str] | None = None,
        exclude_tests: bool = False,
    ) -> dict[str, Any]:
        """Transitive closure analysis — what breaks if these entities change?

        Args:
            entity_ids: Entity IDs to analyse.
            relation_types: Optional filter — only traverse edges of these types
                (e.g. ``["calls", "imports"]``).  Graphify names are normalised
                to lower-case for matching.
            exclude_tests: When True, exclude test/smoke/spec entities from the
                affected set.  This gives a production-only blast radius.
        """
        norm_types = {t.lower() for t in relation_types} if relation_types else None
        all_affected: set[str] = set()
        communities: set[str] = set()
        files: set[str] = set()
        test_files: set[str] = set()

        for eid in entity_ids:
            entity = self._store.get_entity(eid)
            if entity and entity.get("file"):
                (test_files if _is_test_entity(entity) else files).add(entity["file"])
            if entity and entity.get("community"):
                communities.add(entity["community"])
            closure = self._transitive_closure(eid, "in", norm_types, exclude_tests)
            all_affected.update(closure)

        # I1: Filter rationale docstring entities from the affected sets.
        # They have no executable code and cannot "break" when a dependency changes.
        all_affected = {
            eid for eid in all_affected
            if _entity_type_ok(eid, self._store)
        }

        direct: set[str] = set()
        for eid in entity_ids:
            incoming = self._store.get_incoming_relations(eid)
            if norm_types:
                incoming = [
                    r for r in incoming
                    if r.get("type", "").lower() in norm_types
                ]
            for r in incoming:
                if exclude_tests:
                    ent = self._store.get_entity(r["source_id"])
                    if ent and _is_test_entity(ent):
                        continue
                if _entity_type_ok(r["source_id"], self._store):
                    direct.add(r["source_id"])

        transitive = all_affected - direct - set(entity_ids)

        # File count: separate production from test in a single pass
        prod_files: set[str] = set()
        for eid in all_affected:
            entity = self._store.get_entity(eid)
            if entity and entity.get("file"):
                dest = test_files if _is_test_entity(entity) else prod_files
                dest.add(entity["file"])
            if entity and entity.get("community"):
                communities.add(entity["community"])

        # Merge self-files into prod_files
        prod_files.update(files)

        file_count = len(prod_files)
        test_file_count = len(test_files)
        if file_count <= 5:
            risk = "low"
        elif file_count <= 15:
            risk = "medium"
        else:
            risk = "high"

        result: dict[str, Any] = {
            "directly_affected": sorted(direct),
            "transitively_affected": sorted(transitive),
            "affected_communities": sorted(communities),
            "estimated_risk": risk,
            "files_touched": file_count,
        }
        if test_file_count:
            result["test_files_touched"] = test_file_count
            result["note"] = (
                f"{test_file_count} test file(s) also depend on these entities "
                "(excluded from risk calculation)."
            )
        return result

    def _transitive_closure(
        self, start: str, direction: str,
        relation_types: set[str] | None = None,
        exclude_tests: bool = False,
    ) -> set[str]:
        visited: set[str] = set()
        queue: deque[str] = deque([start])
        while queue:
            current = queue.popleft()
            if current in visited:
                continue
            visited.add(current)
            if direction == "in":
                rels = self._store.get_incoming_relations(current)
            else:
                rels = self._store.get_outgoing_relations(current)
            if relation_types:
                rels = [
                    r for r in rels
                    if r.get("type", "").lower() in relation_types
                ]
            neighbors: set[str] = set()
            for r in rels:
                nid = r["source_id"] if direction == "in" else r["target_id"]
                if exclude_tests:
                    ent = self._store.get_entity(nid)
                    if ent and _is_test_entity(ent):
                        continue
                neighbors.add(nid)
            for nid in neighbors:
                if nid not in visited:
                    queue.append(nid)
        visited.discard(start)
        return visited

    def path(
        self,
        source: str,
        target: str,
        relation_types: list[str] | None = None,
        exclude_tests: bool = False,
    ) -> list[dict[str, Any]]:
        """Shortest dependency path between two entities, with optional filters.

        Args:
            source: Starting entity ID.
            target: Target entity ID.
            relation_types: Only follow edges of these types (e.g.
                ``["imports", "imports_from"]`` for import-only paths).
                Without this, paths may traverse test files and shared
                utilities, producing meaningless routes.
            exclude_tests: Skip test/smoke/spec entities during traversal.
        """
        if source == target:
            return []
        norm_types = {t.lower() for t in relation_types} if relation_types else None
        queue: deque[tuple[str, list[dict[str, Any]]]] = deque([(source, [])])
        visited: set[str] = {source}
        while queue:
            current, path_so_far = queue.popleft()
            outgoing = self._store.get_outgoing_relations(current)
            for rel in outgoing:
                if norm_types and rel.get("type", "").lower() not in norm_types:
                    continue
                neighbor = rel["target_id"]
                if exclude_tests:
                    ent = self._store.get_entity(neighbor)
                    if ent and _is_test_entity(ent):
                        continue
                step = {"entity": current, "relation": rel["type"], "next": neighbor}
                if neighbor == target:
                    return [*path_so_far, step]
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, [*path_so_far, step]))
        return []

    def god_nodes(
        self, top_n: int = 10, community: str | None = None,
        exclude_external: bool = False,
    ) -> list[dict[str, Any]]:
        """Most-depended-on entities ranked by in-degree centrality.

        Centrality is based on **in-degree** — the architecturally meaningful
        metric.  Each result includes ``in_degree`` and ``out_degree``.

        When ``exclude_external`` is True, entities without source files
        (Python builtins, stdlib, external libraries) are filtered out.
        This prevents ``str``, ``int``, ``Exception``, etc. from inflating
        the god node list.
        """
        nodes = self._store.get_top_by_centrality(
            limit=top_n * 3 if exclude_external else top_n,
            community=community,
        )
        for node in nodes:
            node["connection_count"] = self._store.connection_count(node["id"])
        if exclude_external:
            nodes = [
                n for n in nodes
                if n.get("file") and not _is_builtin_entity(n)
            ][:top_n]
        return nodes[:top_n]

    def search(self, query: str, top_n: int = 10) -> list[dict[str, Any]]:
        return self._store.search_fts(query, limit=top_n)

    def community(self, entity_id: str) -> dict[str, Any] | None:
        entity = self._store.get_entity(entity_id)
        if entity is None:
            return None
        community_id = entity.get("community")
        if not community_id:
            return {"community": None, "peers": [], "size": 0}
        community_row = self._store.get_community(community_id)
        peers = self._store.get_entities_by_community(community_id)
        return {
            "community": community_row or {"id": community_id},
            "peers": [p for p in peers if p["id"] != entity_id],
            "size": len(peers),
        }

    def stats(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "entity_count": self._store.entity_count(),
            "relation_count": self._store.relation_count(),
            "community_count": self._store.community_count(),
            "graph_version": self._store.version(),
        }
        commit_info = self.commit_info()
        if commit_info:
            result.update(commit_info)
        return result

    def commit_info(self) -> dict[str, Any] | None:
        """Return commit staleness info, or None if unavailable."""
        built_at = self._store.meta_get("built_at_commit")
        if not built_at:
            return None
        current = _git_head_commit()
        return {
            "built_at_commit": built_at,
            "current_commit": current,
            "needs_update": current is not None and built_at != current,
        }

    def explain(self, entity_id: str) -> dict[str, Any]:
        """Template-based explanation of an entity and its neighbourhood.

        Uses the entity's type, relations, community membership, and
        connectivity to produce a human-readable summary — no LLM needed.

        Dependents are split into *production* and *test* groups so that
        test-only coupling does not inflate the apparent impact.
        """
        entity = self._store.get_entity(entity_id)
        if entity is None:
            return {"error": "entity_not_found", "entity_id": entity_id}

        outgoing = self._store.get_outgoing_relations(entity_id)
        incoming = self._store.get_incoming_relations(entity_id)
        community_id = entity.get("community")
        community_info = self.community(entity_id) if community_id else None

        # Live relation counts (B14 fix: stored values may be stale)
        in_deg = len(incoming)
        out_deg = len(outgoing)

        # Categorise relations by type
        rel_types: dict[str, int] = {}
        for rel in outgoing + incoming:
            rtype = rel.get("type", "UNKNOWN")
            rel_types[rtype] = rel_types.get(rtype, 0) + 1

        # Dependencies (outgoing — what this entity depends on)
        dep_entities = [
            self._store.get_entity(r["target_id"]) for r in outgoing
        ]
        dep_names = [_entity_name(e) for e in dep_entities if e]
        deps_prod, deps_test = _split_by_test([e for e in dep_entities if e])

        # Dependents (incoming — what depends on this entity)
        depon_entities = [
            self._store.get_entity(r["source_id"]) for r in incoming
        ]
        depon_prod, depon_test = _split_by_test([e for e in depon_entities if e])
        # I2: Filter builtins/external symbols from production dependents.
        # str, int, Any, Exception are graphify artifacts from type annotations.
        depon_prod = [e for e in depon_prod if not _is_builtin_entity(e)]
        depon_test = [e for e in depon_test if not _is_builtin_entity(e)]

        # Community peers (same community, excluding self)
        peers: list[str] = []
        if community_info and community_info.get("peers"):
            peers = [
                _entity_name(p) for p in community_info["peers"][:8]
            ]

        # Tailor "god node" label to direction
        centrality = entity.get("centrality")
        god_label = ""
        if centrality is not None and centrality > 0.6:
            direction = "hub" if out_deg > in_deg * 2 else \
                        "spoke" if in_deg > out_deg * 2 else "bridge"
            god_label = (
                f"**(God {direction} — in={in_deg}, out={out_deg}, "
                f"centrality {centrality:.2f})**  "
            )

        # Build summary
        lines = [f"**{entity['name']}**  "]
        if god_label:
            lines.append(god_label)
        lines.append(f"Type: `{entity.get('type', 'unknown')}`  ")
        if entity.get("file"):
            loc = f"{entity['file']}"
            if entity.get("line"):
                loc += f":{entity['line']}"
            lines.append(f"Location: `{loc}`  ")
        lines.append(f"Connections: {in_deg} in (depended on) + {out_deg} out (depends on) = {in_deg + out_deg} total  ")

        if rel_types:
            type_summary = ", ".join(
                f"{v}× {k}" for k, v in sorted(rel_types.items(), key=lambda x: -x[1])
            )
            lines.append(f"Relation types: {type_summary}  ")

        if community_id:
            comm_label = community_info.get("community", {}).get("label", community_id) if community_info else community_id
            comm_size = community_info.get("size", 0) if community_info else 0
            lines.append(f"Community: `{community_id}` ({comm_label}, {comm_size} peers)  ")

        if dep_names:
            lines.append(f"  \n**Depends on ({out_deg}):** {', '.join(dep_names[:6])}  ")
        if depon_prod:
            names = [_entity_name(e) for e in depon_prod[:6]]
            lines.append(f"  \n**Depended on by ({len(depon_prod)} production):** {', '.join(names)}  ")
        if depon_test:
            names = [_entity_name(e) for e in depon_test[:4]]
            suffix = f" (+{len(depon_test) - 4} more)" if len(depon_test) > 4 else ""
            lines.append(f"  \n**Also depended on by ({len(depon_test)} test):** {', '.join(names)}{suffix}  ")
        if peers:
            lines.append(f"  \n**Community peers:** {', '.join(peers[:8])}  ")

        return {
            "entity": entity,
            "summary": "".join(lines),
            "in_degree": in_deg,
            "out_degree": out_deg,
            "dependent_count_production": len(depon_prod),
            "dependent_count_test": len(depon_test),
            "community": community_id,
        }

    def diff(self, since: str) -> dict[str, Any]:
        """Entity-level change detection between graph builds.

        ``since`` can be a commit hash (uses ``git diff`` for file-level
        change detection) or ``"last_build"`` (compares against the stored
        entity snapshot from the previous ``load_graph()`` run).

        Returns added, removed, and modified entity lists, plus file-level
        change info and a freshness flag.
        """
        import json as _json

        # Load previous snapshot
        raw_snapshot = self._store.meta_get("entity_snapshot")
        prev_snapshot: dict[str, dict[str, str]] = {}
        if raw_snapshot:
            try:
                prev_snapshot = _json.loads(raw_snapshot)
            except (_json.JSONDecodeError, TypeError):
                pass
        prev_count = int(self._store.meta_get("entity_snapshot_count") or "0")

        # Current entity map
        current_entities: dict[str, dict[str, str]] = {}
        rows = self._store._conn.execute(
            "SELECT id, name, type, file FROM entities"
        ).fetchall()
        for row in rows:
            current_entities[str(row["id"])] = {
                "name": str(row["name"]),
                "type": str(row["type"]),
                "file": str(row["file"]) if row["file"] else None,
            }

        current_ids = set(current_entities.keys())
        prev_ids = set(prev_snapshot.keys())

        added_ids = current_ids - prev_ids
        removed_ids = prev_ids - current_ids

        # Find modified: same ID but different file, or different name
        common_ids = current_ids & prev_ids
        modified_ids: set[str] = set()
        for eid in common_ids:
            cur = current_entities[eid]
            prev = prev_snapshot[eid]
            if cur["file"] != prev.get("file") or cur["name"] != prev.get("name"):
                modified_ids.add(eid)

        # File-level change detection via git
        changed_files: list[str] = []
        git_available = False
        if since and since != "last_build":
            try:
                result = subprocess.run(
                    ["git", "diff", "--name-only", f"{since}..HEAD"],
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode == 0:
                    changed_files = [
                        f.strip() for f in result.stdout.splitlines() if f.strip()
                    ]
                    git_available = True
            except (OSError, subprocess.SubprocessError):
                pass

        # Entities in changed files (more specific than just ID diff)
        file_affected_entities: list[str] = []
        if changed_files:
            changed_set = set(changed_files)
            for eid, info in current_entities.items():
                f = info.get("file")
                if f and f in changed_set:
                    file_affected_entities.append(eid)

        # Build result
        result: dict[str, Any] = {
            "since": since,
            "stats": self.stats(),
            "added_count": len(added_ids),
            "removed_count": len(removed_ids),
            "modified_count": len(modified_ids),
            "file_affected_count": len(file_affected_entities),
            "added_entities": sorted(added_ids)[:50],
            "removed_entities": sorted(removed_ids)[:50],
            "modified_entities": sorted(modified_ids)[:50],
            "snapshot_previous_count": prev_count,
            "snapshot_current_count": len(current_entities),
            "git_changed_files": len(changed_files),
            "git_available": git_available,
        }

        if len(added_ids) > 50:
            result["added_truncated"] = len(added_ids) - 50
        if len(removed_ids) > 50:
            result["removed_truncated"] = len(removed_ids) - 50
        if len(modified_ids) > 50:
            result["modified_truncated"] = len(modified_ids) - 50

        # Freshness
        needs_update = (
            prev_count > 0 and len(added_ids) == len(current_entities)
        )
        if needs_update:
            result["needs_rebuild"] = True
            result["note"] = (
                "Snapshot appears empty or from a different build. "
                "Run load_graph() to refresh the snapshot."
            )

        return result


# ── Helpers ────────────────────────────────────────────────────────────


def _entity_name(entity: dict[str, Any] | None) -> str:
    """Safe entity-name extraction for display."""
    if entity is None:
        return "?"
    return str(entity.get("name", entity.get("id", "?")))


def _git_head_commit() -> str | None:
    """Return the current HEAD commit hash, or None if not in a git repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return None
