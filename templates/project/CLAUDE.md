# FCC Project Rules

- Provider/router: FCC only. Do not add a second default routing proxy.
- Persistent memory owner: MemSearch only when persistent external memory is enabled.
- Code retrieval owner: Token Savior only.
- Claude Context and context-mode: optional, large-repo tools only.
- Critical local facts: CLAUDE.local.md.
- Current state: .fcc/context/handoff.md.
- Durable facts: .fcc/context/facts.md.
- Decisions: .fcc/context/decisions.md.
- Raw logs/tool output: store in the SQLite sidecar and recall by handle.
- Before major work: run /verify-context.
- Startup contract: SessionStart injects compact FCC runtime/context; trust it and do not replay raw transcripts.
- Subagents: use project agents for research, review, and product/logic audits on non-trivial work; skip them for simple edits.
- Optional plugins: use only when configured and task-appropriate. Ralph Loop requires bounded iterations, explicit success criteria, and verification.
