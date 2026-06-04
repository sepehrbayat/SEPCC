# FCC Agent Runtime

- **MANDATORY**: `.fcc/context/quality-gates.md` is a binding quality contract.  Read and apply it before any task — it defines pre-task gates, product-centered rules, red flags, confidence requirements, definition of done, and golden rules.  If the quality gates are missing from this project, request them before proceeding.
- FCC is the provider/router layer; do not add another routing proxy.
- Trust SessionStart injected context first, then `.fcc/context/handoff.md`.
- Durable local facts belong in `CLAUDE.local.md`; committed rules belong in `CLAUDE.md`.
- Persistent memory owner: MemSearch. Code retrieval owner: Token Savior.
- Raw logs/tool output belong in the SQLite sidecar and should be recalled by handle.
- Use `.fcc/sessions.sqlite` and `fcc resume` state for continuity; never replay raw transcripts.
- Use project subagents for research, code review, and product/logic audits when the task is broad or risky.
- Keep trivial tasks single-agent.
- Prefer Claude Code built-in commands before FCC-specific orchestration: `/init`, `/context`, `/compact`, `/diff`, `/code-review`, `/security-review`, `/run`, `/verify`, `/doctor`, `/debug`, `/config`, `/theme`, `/statusline`, `/terminal-setup`, and `/tui fullscreen`.
- Do not rewrite explicit slash commands; let them pass through unchanged.
- Optional plugins must follow `.fcc/plugin-policy.yml`.
- Ralph Loop is optional: use only when configured, bounded, test-verifiable, and capped by max iterations.
- Knowledge graph (fcc-graph MCP): 9 tools available — `fcc_graph_search`, `fcc_graph_neighbors`, `fcc_graph_impact`, `fcc_graph_path`, `fcc_graph_god_nodes`, `fcc_graph_community`, `fcc_graph_entity`, `fcc_graph_stats`, `fcc_graph_explain`. Use them BEFORE reading files: search for entities first, check impact before refactoring, explain before editing unfamiliar code, check stats/staleness before trusting the graph.
