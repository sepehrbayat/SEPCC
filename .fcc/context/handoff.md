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
- user: Alright, commit and push the latest version to Git, and if needed, update the README documentation or anything else as well.
- assistant: This is a major release-level set of changes. Let me update the version and README.
- assistant: Now update the "How agents use it" table to include the new tools:
- assistant: Provider request timed out after 300s.
- Request ID: req_f2e8ebe1fbcb

## Decisions
- Usage sites can never have docstrings, never be "high impact," and never need tests dedicated to them — they're not real entities, they're import statements
- The full graph is never rebuilt from scratch unless explicitly requested
- This is the critical design decision
- file counts, decision extraction from task 1 transcript
- The main session never knows it's being monitored

## Next Steps
- Run /verify-context before major edits.
- Store raw logs in the SQLite sidecar; do not replay them into chat.
