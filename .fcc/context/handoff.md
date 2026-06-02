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
- assistant: **H1 + H2** — Fix lockfile check and cancellation flush in `debugger_pipeline_context` and `detect_task_transition`:
- assistant: **G4** — Add `id` validation to `insert_entity`:
- assistant: **Issue 3** — Add boilerplate filtering to `_shared.summarize_transcript`:
- assistant: Provider request timed out after 300s.
- Request ID: req_f188389e7896

## Decisions
- Persistent memory owner: MemSearch
- Code retrieval owner: Token Savior
- UserPromptSubmit hooks may add enhanced prompt context and visible status, but must not rewrite explicit slash commands
- The full graph is never rebuilt from scratch unless explicitly requested
- This is the critical design decision

## Next Steps
- Run /verify-context before major edits.
- Store raw logs in the SQLite sidecar; do not replay them into chat.
