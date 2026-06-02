"""Graph traversal queries on the knowledge graph."""

from __future__ import annotations

from collections import deque
from typing import Any, Literal

from core.graph.store import GraphStore


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

    def impact(self, entity_ids: list[str]) -> dict[str, Any]:
        all_affected: set[str] = set()
        communities: set[str] = set()
        files: set[str] = set()

        for eid in entity_ids:
            entity = self._store.get_entity(eid)
            if entity and entity.get("file"):
                files.add(entity["file"])
            if entity and entity.get("community"):
                communities.add(entity["community"])
            closure = self._transitive_closure(eid, "in")
            all_affected.update(closure)

        direct: set[str] = set()
        for eid in entity_ids:
            incoming = self._store.get_incoming_relations(eid)
            direct.update({r["source_id"] for r in incoming})

        transitive = all_affected - direct - set(entity_ids)

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

    def _transitive_closure(self, start: str, direction: str) -> set[str]:
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

    def path(self, source: str, target: str) -> list[dict[str, Any]]:
        if source == target:
            return []
        queue: deque[tuple[str, list[dict[str, Any]]]] = deque([(source, [])])
        visited: set[str] = {source}
        while queue:
            current, path_so_far = queue.popleft()
            outgoing = self._store.get_outgoing_relations(current)
            for rel in outgoing:
                neighbor = rel["target_id"]
                step = {"entity": current, "relation": rel["type"], "next": neighbor}
                if neighbor == target:
                    return [*path_so_far, step]
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, [*path_so_far, step]))
        return []

    def god_nodes(self, top_n: int = 10, community: str | None = None) -> list[dict[str, Any]]:
        nodes = self._store.get_top_by_centrality(limit=top_n, community=community)
        for node in nodes:
            node["connection_count"] = self._store.connection_count(node["id"])
        return nodes

    def search(self, query: str, top_n: int = 10) -> list[dict[str, Any]]:
        return self._store.search_fts(query, limit=top_n)

    def community(self, entity_id: str) -> dict[str, Any] | None:
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

    def stats(self) -> dict[str, Any]:
        return {
            "entity_count": self._store.entity_count(),
            "relation_count": self._store.relation_count(),
            "community_count": self._store.community_count(),
            "graph_version": self._store.version(),
        }

    def diff(self, since: str) -> dict[str, Any]:
        return {
            "since": since,
            "stats": self.stats(),
            "note": "Entity-level diff not yet implemented. Use fcc_graph_stats for current state.",
        }
