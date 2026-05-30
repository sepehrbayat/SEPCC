# FCC Agent Runtime

- FCC is the provider/router layer; do not add another routing proxy.
- Trust SessionStart injected context first, then `.fcc/context/handoff.md`.
- Durable local facts belong in `CLAUDE.local.md`; committed rules belong in `CLAUDE.md`.
- Persistent memory owner: MemSearch. Code retrieval owner: Token Savior.
- Raw logs/tool output belong in the SQLite sidecar and should be recalled by handle.
- Use `.fcc/sessions.sqlite` and `fcc resume` state for continuity; never replay raw transcripts.
- Use project subagents for research, code review, and product/logic audits when the task is broad or risky.
- Keep trivial tasks single-agent.
- Optional plugins must follow `.fcc/plugin-policy.yml`.
- Ralph Loop is optional: use only when configured, bounded, test-verifiable, and capped by max iterations.
