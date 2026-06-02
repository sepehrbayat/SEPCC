# Agent Debugger — Design Spec

**Date:** 2026-06-02
**Status:** Design approved, pending implementation plan

## Overview

The Agent Debugger is an FCC pipeline that monitors subagent development output,
detects when the agent moves from one task to the next, and dispatches a
debugger→fixer subagent chain to analyze and repair the previous task's work —
all without blocking the user's forward progress.

## Motivation

SEPCC agents today have no systematic post-completion review. When an agent
finishes a task and the user moves on to the next, any bugs, incomplete work,
or process violations in the first task persist silently — surfaced only when
someone encounters the broken code later. The debugger pipeline closes this gap
by making post-task review automatic, non-blocking, and self-repairing.

## Architecture

### Component Map

```
core/debugger/
├── __init__.py              # Public API: trigger_chain, debug_report_path
├── trigger.py               # Task transition detection + pending task capture
├── report.py                # DebugReport + FixReport schemas

.claude/agents/
├── fcc-agent-debugger.md    # Debugger subagent definition
├── fcc-agent-fixer.md       # Fixer subagent definition

scripts/hooks/
└── user_prompt_submit.py    # MODIFIED: inject debugger pipeline on transition
```

**Five new files, one modified hook. Zero new dependencies.**

### Component Responsibilities

**`trigger.py`** — Runs inside hooks (deterministic, <500ms, no LLM):
- Compares the new user prompt against the previous task title
- Detects task transitions using keyword overlap analysis
- Captures pending task metadata to `.fcc/debugger/pending/<slug>.json`
- Handles cancellation detection, lockfile management, queue ordering

**`report.py`** — Defines the structured data contracts:
- `DebugReport`: findings categorized as correctness/completeness/process
  with severity, file, line, evidence, and suggested fix per finding
- `FixReport`: applied fixes with verification status and commit references

**`fcc-agent-debugger`** — Subagent that performs deep analysis:
- Reads the pending task JSON, full transcript JSONL, and git diff
- Analyzes correctness (bugs, logic errors, type errors, test failures)
- Analyzes completeness (missing features, TODOs, stubs, coverage gaps)
- Analyzes process (CLAUDE.md compliance, conventions, decision documentation)
- Produces a structured `DebugReport` saved to `.fcc/debugger/reports/`

**`fcc-agent-fixer`** — Subagent that repairs issues:
- Runs in git worktree isolation to never conflict with active work
- Fixes findings in priority order (correctness → completeness → process)
- Runs tests after each fix batch, blocks on failure
- Commits fixes, writes `FixReport`, cleans up worktree

**Modified `user_prompt_submit.py`** — Adds transition detection + injection:
- After existing prompt enhancement and routing hint logic
- Detects task transitions, captures pending state, injects dispatch
  instructions as additional_context

## Data Flow

### End-to-End Pipeline

```
Task 1 subagent completes
       │
       ▼
SubagentStop hook (unchanged) — regenerates handoff
       │
       ▼
User asks for task 2
       │
       ▼
UserPromptSubmit hook fires
  ├─ Existing: enhance prompt, routing hints, session naming
  └─ NEW: detect_task_transition(root, prompt)
       │
       ▼
  Transition detected? ──No──▶ Skip, proceed normally
       │
      Yes
       │
       ▼
  capture_pending_task() → .fcc/debugger/pending/<slug>.json
       │
       ▼
  inject_debugger_pipeline() → additional_context
    "PIPELINE: Dispatch fcc-agent-debugger → fcc-agent-fixer
     in background. Continue with task 2 in parallel."
       │
       ▼
┌─────────────────────────────────────────────────────┐
│  FOREGROUND: Main agent works on task 2              │
│                                                      │
│  BACKGROUND CHAIN:                                    │
│  ┌────────────────────────────────────────┐          │
│  │ fcc-agent-debugger                      │          │
│  │ Reads transcript + git diff + tests     │          │
│  │ Produces DebugReport                    │          │
│  └──────────────┬─────────────────────────┘          │
│                 │                                     │
│  ┌──────────────▼─────────────────────────┐          │
│  │ fcc-agent-fixer                         │          │
│  │ Git worktree isolation                  │          │
│  │ Fixes in priority order                 │          │
│  │ Tests after each batch                  │          │
│  │ Commits, writes FixReport               │          │
│  └────────────────────────────────────────┘          │
└─────────────────────────────────────────────────────┘
       │
       ▼
SubagentStop fires for debugger → handoff updated
SubagentStop fires for fixer → handoff updated
       │
       ▼
Handoff now contains debug + fix summaries
```

### Pending Task Payload

Saved to `.fcc/debugger/pending/<timestamp>-<task-slug>.json`:

```json
{
  "task_name": "fix-login-bug",
  "task_description": "fix the bug in the auth token refresh",
  "session_id": "abc123def456",
  "transcript_path": "/path/to/transcript.jsonl",
  "started_at": "2026-06-02T14:30:00Z",
  "completed_at": "2026-06-02T14:37:22Z",
  "commit_range": "abc123..def456",
  "files_changed": [
    "src/auth/manager.py",
    "src/auth/refresh.py",
    "tests/auth/test_refresh.py"
  ],
  "test_results": {
    "ran": 12,
    "passed": 10,
    "failed": 2,
    "failures": ["test_refresh_expired_token", "test_refresh_race_condition"]
  }
}
```

### DebugReport Schema

```python
class Finding:
    id: str                    # CORR-001, COMP-002, PROC-003
    severity: Literal["high", "medium", "low"]
    file: str                  # Relative path
    line: int | None           # Line number if applicable
    description: str           # What is wrong
    evidence: str              # What proves it (code, transcript excerpt)
    suggested_fix: str         # How to fix it

class DebugReport:
    task_name: str
    analyzed_at: str           # ISO timestamp
    files_changed: list[str]
    correctness: list[Finding]
    completeness: list[Finding]
    process: list[Finding]
    meta: DebugReportMeta

class DebugReportMeta:
    risk_level: Literal["low", "medium", "high"]
    fix_priority: list[str]    # Ordered finding IDs
    total_findings: int
    tests_passing_before: int | None
    tests_total: int | None
```

### FixReport Schema

```python
class FixEntry:
    finding_id: str
    action: str                # What was changed
    verified: bool             # Tests passed after fix?
    commit: str | None         # Git commit hash

class FixReport:
    task_name: str
    debug_report: str          # Path to DebugReport
    fixed_at: str              # ISO timestamp
    fixes_applied: list[FixEntry]
    fixes_skipped: list[FixEntry]
    tests_after: dict | None   # Test results after all fixes
    worktree_branch: str       # Branch name for merge
```

## Injection Format

The hook injects via `additional_context` (up to 500 characters, fitting within
the existing 3600-char budget):

```
PIPELINE: The previous task '<name>' completed and should be debugged.
Dispatch in exact order:
1. fcc-agent-debugger (run_in_background: true) — analyze
   Debug file: .fcc/debugger/pending/<slug>.json
2. fcc-agent-fixer (run_in_background: true) — fix issues
   Uses git worktree isolation. You'll be notified when done.
Continue with the current task in parallel.
```

## Transition Detection

### Algorithm

```python
def detect_task_transition(root: Path, prompt: str) -> Path | None:
    # Skip slash commands and empty prompts
    name = session_name_from_prompt(prompt)
    if not name or not prompt.lstrip() or prompt.lstrip().startswith("/"):
        return None

    # Skip cancellation intents
    if any(kw in prompt.lower() for kw in
           ("skip debug", "cancel debug", "don't debug", "never mind")):
        flush_pending_to_skipped(root)
        return None

    # Get what the agent was just working on
    previous = get_last_completed_task(root)
    if not previous:
        return None

    # Check if this is genuinely a new task
    if _tasks_are_same(name, previous["name"]):
        return None

    # Check that real work was done (subagent involved, files changed)
    if not previous.get("files_changed"):
        return None

    return capture_pending_task(root, previous)
```

### Continuation vs. Transition

Keyword overlap between old and new task names determines the boundary:
- ≥40% shared significant terms → continuation (no debug pipeline)
- <40% shared → new task (trigger debug pipeline)

Examples:
- "fix login bug" → "also add a test for it" → CONTINUATION
- "fix login bug" → "what file handles auth?" → CONTINUATION
- "fix login bug" → "add rate limiting to API" → TRANSITION
- "refactor auth module" → "now build the dashboard" → TRANSITION

### `debugger_pipeline_context()` — Called from Hook

This is the entry point that `user_prompt_submit.py` calls:

```python
def debugger_pipeline_context(prompt: str, root: Path) -> str:
    """Build the debugger pipeline injection, if a transition is detected."""
    # Primary: check for transition from the just-completed task
    pending_path = detect_task_transition(root, prompt)
    if pending_path:
        return _format_pipeline_injection(pending_path)

    # Fallback: check queue for pending tasks from earlier rapid switching
    if _has_pending_queue(root) and not _lockfile_exists(root):
        next_pending = _pop_next_pending(root)
        if next_pending:
            return _format_pipeline_injection(next_pending)

    return ""
```

This function handles both the primary transition case and the queue
drain fallback, so the hook only needs a single call site.

## Trigger Internals

### How `get_last_completed_task()` Works

Reads from two sources in `.fcc/`:

1. **sessions.sqlite** — queries the most recent session with `status = 'resumable'`
   that has a `current_task_title` set. This gives the task name and session ID.

2. **handoff.md** — reads the `## Current State` section to find the last subagent's
   transcript path and any file-change summaries. If the handoff mentions
   "subagent handoff updated", a subagent was involved.

3. **git diff** — runs `git diff --name-only HEAD~1` to find recently changed files.
   If there are no changed files (e.g., the task was research-only, conversation,
   or a subagent that produced no code), returns `files_changed: []`.

The function returns `None` if: no previous session exists, the previous session
has no task title, or no files were changed (nothing to debug).

### Lockfile Format

`.fcc/debugger/lock` contains the PID of the currently running fixer subagent:

```
12345
```

The lock is acquired atomically using `O_CREAT | O_EXCL`. If the file exists,
the PID is checked against the process table. If the process is dead (stale lock),
the lockfile is removed and re-acquired. A 30-minute absolute timeout prevents
orphaned locks from persisting.

### Queue Drain

When tasks arrive in rapid succession, `.fcc/debugger/pending/` accumulates
entries. Each `SubagentStop` for a fixer subagent triggers a check:
if `.fcc/debugger/pending/` has more entries, and no lockfile exists,
the hook injects a dispatch instruction for the next pending task.
This means the pipeline self-drains without the main agent needing to
remember to check the queue.

## Error Handling

| Scenario | Behavior |
|----------|----------|
| No previous task exists | Hook is a no-op, no injection |
| Ambiguous transition | Conservative: treat as continuation, don't interrupt |
| No subagent used, no files changed | Skip — nothing to debug |
| Debugger subagent fails/crashes | Fixer detects missing/malformed report, writes failure notice to handoff, moves pending to `failed/` |
| Fixer and main agent touch same files | Fixer uses git worktree — zero conflict. Fixes committed on branch, not auto-merged |
| Rapid task switching (3+ tasks in succession) | Queue in `.fcc/debugger/pending/`, process sequentially, lockfile prevents concurrent fixers |
| User cancels pipeline | Keywords detected in UserPromptSubmit, pending flushed to `skipped/`, agent proceeds |
| No test suite available | Debugger skips test dimension, fixer flags all fixes as `verified: false` |

## File System Layout

```
.fcc/debugger/
├── pending/           # Tasks awaiting debugger analysis
│   └── 2026-06-02T1430-fix-login-bug.json
├── reports/           # DebugReport output from debugger subagent
│   └── fix-login-bug.json
├── fixes/             # FixReport output from fixer subagent
│   └── fix-login-bug.json
├── failed/            # Debug reports that couldn't be processed
├── skipped/           # Tasks user explicitly skipped
└── lock               # Lockfile: prevents concurrent fixer execution
```

## Hook Integration

### Modified: `user_prompt_submit.py`

```python
def main() -> None:
    data = read_hook_input()
    prompt = str(data.get("prompt", ""))
    root = project_root(data)

    # Existing logic (unchanged)
    name = session_name_from_prompt(prompt)
    name_active_session(root, name)
    enhancement_context, enhancement_message = prompt_enhancement_outputs(prompt, root)

    # NEW: Debugger pipeline injection
    pipeline_context = debugger_pipeline_context(prompt, root)

    payload = " ".join(
        part for part in (
            enhancement_context,
            prompt_routing_hint(prompt),
            pipeline_context,          # Added
        ) if part
    )
    emit_hook_json(
        "UserPromptSubmit",
        additional_context=payload,
        system_message=enhancement_message,
    )
```

### Unchanged Hooks

- `session_start.py` — No changes
- `stop.py` — No changes
- `subagent_stop.py` — No changes (already processes subagent transcripts into handoff)
- `precompact.py` — No changes (already preserves Must Not Forget)

The debugger and fixer subagents produce transcripts that the existing
`SubagentStop` hook processes automatically — their findings appear in
handoff and decisions without any new code.

### Queue Drain via SubagentStop

While `subagent_stop.py` itself is unchanged, its existing behavior enables
queue drain. When a fixer subagent completes, `SubagentStop` fires and
regenerates the handoff. On the next `UserPromptSubmit` (even for the
same task), `debugger_pipeline_context()` checks:
1. Is there a next entry in `.fcc/debugger/pending/`?
2. Is the lockfile absent (no fixer currently running)?
3. If yes to both → inject dispatch for the next pending task

This means the queue drains naturally — each user prompt acts as a
checkpoint that advances the debug pipeline forward. No background
process watcher needed. A queue item that sits in `pending/` for
more than 6 hours is automatically moved to `failed/` (stale).

## Subagent Definitions

### fcc-agent-debugger

- **Tools:** Read, Grep, Glob, Bash
- **Input:** `.fcc/debugger/pending/<slug>.json`
- **Output:** `.fcc/debugger/reports/<task-slug>.json` (DebugReport)
- **Analysis:** correctness → completeness → process
- **Rules:** Be specific (file + line + evidence). Don't flag style preferences. Empty report is valid.

### fcc-agent-fixer

- **Tools:** Read, Write, Edit, Grep, Glob, Bash
- **Setup:** `git worktree add --detach .claude/worktrees/fixer-<slug> HEAD`
- **Input:** `.fcc/debugger/reports/<task-slug>.json` (DebugReport)
- **Output:** `.fcc/debugger/fixes/<task-slug>.json` (FixReport)
- **Protocol:** Fix in priority order. Test after each batch. Commit when done.
- **Isolation:** Never touches main working tree. Worktree only.
- **Cleanup:** `git worktree remove .claude/worktrees/fixer-<slug> --force`

## Testing Strategy

### Layer 1: Trigger Logic (unit, <1s)
- Transition detection accuracy (7 cases)
- Payload serialization correctness
- Cancellation detection
- Queue management

### Layer 2: Report Schema (unit, <1s)
- DebugReport round-trip serialization
- Validation of required fields
- Risk level enum constraints

### Layer 3: Hook Injection (integration, uses real hook pipeline)
- Injection format compliance
- Character budget adherence
- No-injection-when-no-transition

### Layer 4: Subagent Definitions (spec tests)
- Required tools present
- Input/output paths correct
- Worktree isolation instructions present

### Layer 5: End-to-End (uses real subagents, API cost)
- Full pipeline with known bug → detected → fixed
- Perfect task → empty report → no fixes
- Worktree isolation verified
- Handoff updated with summaries

## Non-Goals (for v1)

- Cross-session debugger state (debug data is per-session)
- Real-time transcript streaming (analyzes completed transcripts only)
- Automatic merge of fixer branches (user/agent decides when to merge)
- Fixer for non-code tasks (research, conversation, planning — debugger only fires for code-producing tasks)
- Daemon-based monitoring (deferred to future evolution)
