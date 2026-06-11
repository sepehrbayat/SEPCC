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
- | **Adaptive PreCompact** | Transcript-aware entity injection in `precompact.py` |
- | **Multi-entity routing** | Aggregate centrality in `_graph_routing_hint()` |
- | **Test infrastructure** | 6 libraries installed, 62 advanced tests (hypothesis + freezegun + syrupy + mock) |
- | **OpenCode tests** | 6 unit tests for OpenCode Zen provider |
- | **Graph impact** | 25 queries, ~35 file reads saved, ~35 min saved, 93% finding accuracy |

## Decisions
- Usage sites can never have docstrings, never be "high impact," and never need tests dedicated to them — they're not real entities, they're import statements
- Pick up the last task as if the break never happened
- The full graph is never rebuilt from scratch unless explicitly requested
- This is the critical design decision
- file counts, decision extraction from task 1 transcript

## Next Steps
- Run /verify-context before major edits.
- Store raw logs in the SQLite sidecar; do not replay them into chat.
