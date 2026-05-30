# Verify Context

Check that:

- `CLAUDE.local.md` contains required local facts.
- `.fcc/context/handoff.md` has current state and next step.
- `.fcc/context/decisions.md` records durable decisions.
- `.mcp.json` has Token Savior as the baseline code retrieval server.
- Only one persistent memory owner is active when persistent memory is enabled: MemSearch.

Report stale or conflicting context before editing code.
