# FCC Handoff

## Must Not Forget
- Persistent memory owner: MemSearch.
- Code retrieval owner: Token Savior.
- FCC remains the provider/router layer.
- Claude Code hooks cannot replace submitted user text; UserPromptSubmit sends enhanced text as additional context plus a visible system message.
- Keep critical machine-local facts in `CLAUDE.local.md`, not raw chat or transcripts.
# Project Facts
- Keep critical machine-local facts in CLAUDE.local.md first.
- Keep this file for durable project facts that should be safe to share with future sessions.

## Current State
- No transcript summary was available.

## Decisions
- Persistent memory owner: MemSearch
- Code retrieval owner: Token Savior
- `to_dict()` (line 92) never serializes it
- `from_dict()` (line 118) never restores it
- The `/enhance` command accesses internal `CLISessionManager` attributes via `getattr` with default fallbacks:

## Next Steps
- Run /verify-context before major edits.
- Store raw logs in the SQLite sidecar; do not replay them into chat.
