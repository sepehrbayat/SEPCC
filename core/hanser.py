"""Hanser — High-accuracy Annotation & Semantic Enrichment Router.

Graph-aware prompt enrichment pipeline. Maps entities from the user's prompt
to the knowledge graph, fetches rich context (docstrings, centrality,
dependencies), and produces a structured enrichment block and complexity
score. Unlike the prompt enhancer, Hanser is purely graph-native — no LLM
call needed.

Usage::

    from core.hanser import Hanser

    h = Hanser.from_project(Path("."))
    enrichment = h.enrich("fix the Settings validation in model_router.py")
    print(enrichment.context_block)
    print(enrichment.complexity_score)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class EnrichmentResult:
    """Result of Hanser prompt analysis."""

    # Matched entities
    matched_entities: list[dict[str, Any]] = field(default_factory=list)

    # Computed metrics
    complexity_score: float = 0.0  # 0.0–1.0
    cross_community_count: int = 0
    god_node_count: int = 0
    suggested_tier: str = "sonnet"

    # Enrichment outputs
    context_block: str = ""
    entity_summaries: list[str] = field(default_factory=list)

    # Diagnostics
    prompt_words_parsed: int = 0
    search_terms: list[str] = field(default_factory=list)


class Hanser:
    """Graph-aware prompt analysis and enrichment engine.

    Maps entities from the user prompt to the knowledge graph and produces
    structured context enrichment plus a complexity score for routing.
    """

    def __init__(self, graph_query: Any, project_root: Path):
        self._query = graph_query
        self._root = project_root

    @classmethod
    def from_project(cls, root: Path) -> Hanser | None:
        """Create a Hanser instance from a project root, or None if no graph."""
        try:
            from core.graph import load_graph
            from core.graph.query import GraphQuery
        except ImportError:
            return None

        graph_json = root / ".fcc" / "graph" / "graph.json"
        if not graph_json.is_file():
            return None

        try:
            store = load_graph(root)
            query = GraphQuery(store)
            return cls(query, root)
        except Exception:
            return None

    def enrich(self, prompt: str) -> EnrichmentResult:
        """Analyze a prompt and produce structured enrichment.

        Args:
            prompt: The raw user prompt text.

        Returns:
            EnrichmentResult with matched entities, complexity score,
            suggested tier, and a context block for injection.
        """
        if not prompt.strip():
            return EnrichmentResult()

        # Phase 1: Parse
        words = [w.lower() for w in prompt.split() if len(w) > 2]
        if not words:
            return EnrichmentResult(prompt_words_parsed=0)

        # Phase 2: Search graph for matching entities
        seen_ids: set[str] = set()
        matched: list[dict[str, Any]] = []
        search_terms: list[str] = []

        for word in words[:12]:
            search_terms.append(word)
            for r in self._query.search(word, top_n=3):
                if r["id"] not in seen_ids:
                    seen_ids.add(r["id"])
                    matched.append(r)

        if not matched:
            return EnrichmentResult(
                prompt_words_parsed=len(words),
                search_terms=search_terms,
                context_block="",
                suggested_tier="haiku",
            )

        # Phase 3: Enrich — get explanation for top entities
        code_entities = [e for e in matched if e.get("type") == "code"]
        if not code_entities:
            code_entities = matched[:5]  # Fallback to any matched entities

        # Sort by centrality (god nodes first)
        code_entities.sort(
            key=lambda e: float(e.get("centrality", 0) or 0), reverse=True
        )

        entity_summaries: list[str] = []
        for e in code_entities[:8]:
            try:
                exp = self._query.explain(e["id"])
                if "summary" in exp:
                    entity_summaries.append(exp["summary"])
            except Exception:
                # Entity explanation failed — skip silently
                pass

        # Phase 4: Compute complexity metrics
        centralities = [
            float(e.get("centrality", 0) or 0) for e in code_entities
        ]
        total_centrality = sum(centralities)
        max_centrality = max(centralities) if centralities else 0
        communities = {
            e.get("community") for e in code_entities if e.get("community")
        }
        god_nodes = [e for e in code_entities
                     if (float(e.get("centrality", 0) or 0)) > 0.5]

        # Complexity formula: weighted sum where centrality is primary signal
        complexity = min(
            1.0,
            (total_centrality * 0.5)
            + (len(communities) * 0.03)
            + (len(god_nodes) * 0.20)
            + (len(code_entities) * 0.02),
        )

        # Phase 5: Determine tier
        if complexity > 0.5 or max_centrality > 0.8 or len(god_nodes) > 2:
            tier = "opus"
        elif complexity > 0.15 or max_centrality > 0.3 or len(communities) > 2:
            tier = "sonnet"
        else:
            tier = "haiku"

        # Phase 6: Build context block
        lines = ["[Hanser: Graph-Aware Context]"]

        # Summary stats
        lines.append(
            f"Matched {len(code_entities)} entities in "
            f"{len(communities)} communities. "
            f"{len(god_nodes)} god nodes. "
            f"Complexity: {complexity:.2f}."
        )

        # Entity list
        for e in code_entities[:6]:
            file = e.get("file", "?")
            cent = float(e.get("centrality", 0) or 0)
            god_str = " [GOD]" if cent > 0.5 else ""
            lines.append(f"  - `{e['name']}` ({file}) cent={cent:.3f}{god_str}")

        # Top god node context
        if god_nodes:
            lines.append(f"\nGod nodes affected:")
            for g in god_nodes[:3]:
                expand = self._query.explain(g["id"])
                if "summary" in expand:
                    # Include just the first 2 lines of each god explanation
                    summary_lines = expand["summary"].split("  ")
                    short = "  ".join(summary_lines[:2]).strip()
                    lines.append(f"  {short}")

        # Community context
        if len(communities) > 1:
            lines.append(
                f"\nCross-community: {len(communities)} communities — "
                f"change may have broad effects."
            )

        context = "\n".join(lines)

        return EnrichmentResult(
            matched_entities=code_entities,
            complexity_score=round(complexity, 3),
            cross_community_count=len(communities),
            god_node_count=len(god_nodes),
            suggested_tier=tier,
            context_block=context,
            entity_summaries=entity_summaries,
            prompt_words_parsed=len(words),
            search_terms=search_terms,
        )

    def enrich_with_context(self, prompt: str) -> str:
        """Return just the context block for hook injection."""
        return self.enrich(prompt).context_block

    def complexity(self, prompt: str) -> float:
        """Return just the complexity score."""
        return self.enrich(prompt).complexity_score
