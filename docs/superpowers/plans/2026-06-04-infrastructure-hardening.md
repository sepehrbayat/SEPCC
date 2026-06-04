# Graphify + Infrastructure Hardening Plan

> **For agentic workers:** Execute inline, task by task, verifying at each step.

**Goal:** Harden all 9 findings from the June 2026 audit — graph freshness, edge verification, context injection, graph diff, isolated nodes, prompt observability, smarter routing, self-healing context, and Hanser pipeline.

**Architecture:** Each task is self-contained. Near-term (1-3) fixes immediate gaps. Medium-term (4-6) adds new capabilities. Strategic (7-9) enhances existing behavior.

---

### Task 1: Refresh the graph
- Run `graphify update .` to bring graph to current HEAD

### Task 2: Verify 151 inferred Settings edges
- Query store.db for Settings entities with INFERRED edges, cross-check against source code

### Task 3: Add changed_files to SessionStart hook
- Modify `scripts/hooks/session_start.py` to pass `git diff --name-only` to `build_session_bootstrap()`

### Task 4: Implement entity-level graph diff
- Replace stub in `core/graph/query.py:diff()` with real entity-level comparison

### Task 5: Audit top 50 isolated nodes
- Query store.db for isolated nodes, categorize, report

### Task 6: Add fcc prompts stats command
- New CLI entry point `fcc-prompts-stats` reading TRACE logs for enhancement metrics

### Task 7: More aggressive graph-driven routing
- Multi-entity matching in router — aggregate centrality scores across all matched entities

### Task 8: Self-healing PreCompact context
- Extract entities from conversation, inject only relevant graph context

### Task 9: Define/build Hanser prompt pipeline
- New module `core/hanser.py` — graph-aware prompt analysis and enrichment pipeline
