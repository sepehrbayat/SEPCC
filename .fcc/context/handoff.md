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
- | `scripts/graph/mcp_server.py` | B2: cached store, B22: missing/corrupted messages, B23: param validation, B24: parse error responses |
- | `cli/context_doctor.py` | B25: threshold message |
- | `tests/graph/test_*.py` | 22 new tests covering all 31 bugs |
- user: fix the last issue
- assistant: Now let me test this with `circuit_breaker` specifically:

## Decisions
- The full graph is never rebuilt from scratch unless explicitly requested
- This is the critical design decision
- file counts, decision extraction from task 1 transcript
- The main session never knows it's being monitored
- user: Given your understanding of the project and of yourself as an agent, you’re in the best position to judge it and, in my opinion, you should choose the best strategy yourself

## Next Steps
- Run /verify-context before major edits.
- Store raw logs in the SQLite sidecar; do not replay them into chat.
