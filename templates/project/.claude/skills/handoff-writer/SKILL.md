---
name: handoff-writer
description: Update the compact FCC handoff at the end of meaningful work or before compaction.
---

# Handoff Writer

Write `.fcc/context/handoff.md` with these sections:

- Must Not Forget
- Current State
- Decisions
- Next Steps

Keep bullets concise. Put critical local-machine facts in `CLAUDE.local.md`, not in chat or raw transcripts. Put raw logs in the SQLite sidecar and reference handles.
