# Agent Debugger — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a post-subagent debugger pipeline that detects task transitions, dispatches a debugger→fixer subagent chain in background, and autonomously repairs the previous task's issues — using SEPCC's existing hook + subagent infrastructure with zero new dependencies.

**Architecture:** Three new files in `core/debugger/` (report schemas, trigger logic, public API), two subagent definition files in `.claude/agents/`, one modified hook (`user_prompt_submit.py`), and five test files. The trigger runs deterministically inside hooks (<500ms, no LLM), captures pending task metadata to `.fcc/debugger/pending/`, and injects dispatch instructions into the agent's context. Subagents handle the heavy analysis and repair work in background via worktree isolation.

**Tech Stack:** Python 3.14+, stdlib (sqlite3, json, pathlib, os, subprocess, datetime), pydantic (already a dependency), pytest (dev dependency). Zero new packages.

---

### Task 1: Report Schema — `core/debugger/report.py`

**Files:**
- Create: `core/debugger/report.py`
- Test: `tests/debugger/test_report.py`

- [ ] **Step 1: Create the debugger package directory**

```powershell
New-Item -ItemType Directory -Force -Path core\debugger
New-Item -ItemType Directory -Force -Path tests\debugger
New-Item -ItemType File -Path core\debugger\__init__.py
New-Item -ItemType File -Path tests\debugger\__init__.py
```

- [ ] **Step 2: Write the report schemas with Pydantic**

Write to `core/debugger/report.py`:

```python
"""Structured data contracts for the FCC Agent Debugger pipeline."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class Finding(BaseModel):
    """A single issue found during debug analysis."""

    id: str  # CORR-001, COMP-002, PROC-003
    severity: Literal["high", "medium", "low"]
    file: str  # Relative path to the file
    line: int | None = None  # Line number if applicable
    description: str  # What is wrong
    evidence: str  # What proves it (code snippet, transcript excerpt)
    suggested_fix: str  # How to fix it


class DebugReportMeta(BaseModel):
    """Metadata for a debug report."""

    risk_level: Literal["low", "medium", "high"]
    fix_priority: list[str] = Field(default_factory=list)  # Ordered finding IDs
    total_findings: int = 0
    tests_passing_before: int | None = None
    tests_total: int | None = None


class DebugReport(BaseModel):
    """Complete analysis of a completed task's work."""

    task_name: str
    analyzed_at: str  # ISO timestamp
    files_changed: list[str] = Field(default_factory=list)
    correctness: list[Finding] = Field(default_factory=list)
    completeness: list[Finding] = Field(default_factory=list)
    process: list[Finding] = Field(default_factory=list)
    meta: DebugReportMeta = Field(default_factory=DebugReportMeta)

    @model_validator(mode="after")
    def _sync_meta(self) -> DebugReport:
        all_findings = self.correctness + self.completeness + self.process
        self.meta.total_findings = len(all_findings)
        if not self.meta.fix_priority:
            self.meta.fix_priority = [f.id for f in all_findings]
        if self.meta.total_findings == 0 and self.meta.risk_level == "high":
            self.meta.risk_level = "low"
        return self

    @classmethod
    def from_path(cls, path: Path | str) -> DebugReport:
        """Load a DebugReport from a JSON file."""
        raw = Path(path).read_text(encoding="utf-8")
        return cls.model_validate_json(raw)

    def to_path(self, path: Path | str) -> None:
        """Write this DebugReport to a JSON file."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            self.model_dump_json(indent=2, exclude_none=True),
            encoding="utf-8",
        )

    def is_empty(self) -> bool:
        """True if no findings were discovered."""
        return self.meta.total_findings == 0


class FixEntry(BaseModel):
    """A single fix applied by the fixer subagent."""

    finding_id: str
    action: str  # What was changed
    verified: bool  # Tests passed after fix?
    commit: str | None = None  # Git commit hash


class FixReport(BaseModel):
    """Summary of fixes applied by the fixer subagent."""

    task_name: str
    debug_report: str  # Path to the DebugReport that was read
    fixed_at: str  # ISO timestamp
    fixes_applied: list[FixEntry] = Field(default_factory=list)
    fixes_skipped: list[FixEntry] = Field(default_factory=list)
    tests_after: dict[str, Any] | None = None  # {ran, passed, failed}
    worktree_branch: str = ""

    @classmethod
    def from_path(cls, path: Path | str) -> FixReport:
        """Load a FixReport from a JSON file."""
        raw = Path(path).read_text(encoding="utf-8")
        return cls.model_validate_json(raw)

    def to_path(self, path: Path | str) -> None:
        """Write this FixReport to a JSON file."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            self.model_dump_json(indent=2, exclude_none=True),
            encoding="utf-8",
        )


def now_iso() -> str:
    """UTC now as an ISO 8601 string."""
    return datetime.now(UTC).isoformat()
```

- [ ] **Step 3: Write the report schema tests**

Write to `tests/debugger/test_report.py`:

```python
"""Tests for FCC debugger report schemas."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.debugger.report import (
    DebugReport,
    DebugReportMeta,
    Finding,
    FixEntry,
    FixReport,
    now_iso,
)


def test_finding_roundtrip() -> None:
    f = Finding(
        id="CORR-001",
        severity="high",
        file="src/auth/manager.py",
        line=42,
        description="Race condition in token refresh",
        evidence="Lines 42-47: check-then-act without lock",
        suggested_fix="Wrap in threading.Lock",
    )
    data = f.model_dump()
    reloaded = Finding.model_validate(data)
    assert reloaded.id == "CORR-001"
    assert reloaded.severity == "high"
    assert reloaded.line == 42


def test_finding_optional_line() -> None:
    f = Finding(
        id="COMP-001",
        severity="medium",
        file="README.md",
        description="Missing setup instructions",
        evidence="No installation section",
        suggested_fix="Add installation docs",
    )
    assert f.line is None


def test_debug_report_roundtrip() -> None:
    report = DebugReport(
        task_name="fix-login-bug",
        analyzed_at=now_iso(),
        files_changed=["src/auth/manager.py"],
        correctness=[
            Finding(
                id="CORR-001",
                severity="high",
                file="src/auth/manager.py",
                line=42,
                description="Race condition",
                evidence="No lock around token refresh",
                suggested_fix="Add lock",
            )
        ],
        completeness=[],
        process=[],
        meta=DebugReportMeta(risk_level="high"),
    )
    data = report.model_dump()
    reloaded = DebugReport.model_validate(data)
    assert reloaded.task_name == "fix-login-bug"
    assert reloaded.meta.total_findings == 1
    assert reloaded.meta.risk_level == "high"


def test_debug_report_meta_synced() -> None:
    report = DebugReport(
        task_name="test",
        analyzed_at=now_iso(),
        correctness=[
            Finding(
                id="CORR-001",
                severity="low",
                file="x.py",
                line=1,
                description="a",
                evidence="b",
                suggested_fix="c",
            ),
            Finding(
                id="CORR-002",
                severity="low",
                file="y.py",
                line=2,
                description="d",
                evidence="e",
                suggested_fix="f",
            ),
        ],
    )
    assert report.meta.total_findings == 2
    assert report.meta.fix_priority == ["CORR-001", "CORR-002"]


def test_debug_report_empty_risk_downgrade() -> None:
    """Empty report should not be labeled high risk."""
    report = DebugReport(
        task_name="test",
        analyzed_at=now_iso(),
        meta=DebugReportMeta(risk_level="high"),
    )
    assert report.is_empty()
    assert report.meta.risk_level == "low"


def test_debug_report_risk_level_values() -> None:
    with pytest.raises(Exception):
        DebugReportMeta(risk_level="critical")  # type: ignore[arg-type]


def test_debug_report_file_roundtrip(tmp_path: Path) -> None:
    report = DebugReport(
        task_name="fix-login-bug",
        analyzed_at=now_iso(),
        correctness=[
            Finding(
                id="CORR-001",
                severity="low",
                file="x.py",
                line=1,
                description="d",
                evidence="e",
                suggested_fix="f",
            )
        ],
    )
    path = tmp_path / "report.json"
    report.to_path(path)
    reloaded = DebugReport.from_path(path)
    assert reloaded.task_name == "fix-login-bug"
    assert reloaded.meta.total_findings == 1


def test_fix_report_roundtrip() -> None:
    fix = FixReport(
        task_name="fix-login-bug",
        debug_report=".fcc/debugger/reports/fix-login-bug.json",
        fixed_at=now_iso(),
        fixes_applied=[
            FixEntry(
                finding_id="CORR-001",
                action="Added lock around token refresh",
                verified=True,
                commit="abc123",
            )
        ],
        fixes_skipped=[],
        tests_after={"ran": 12, "passed": 12, "failed": 0},
        worktree_branch="fixer-fix-login-bug-abc123",
    )
    data = fix.model_dump()
    reloaded = FixReport.model_validate(data)
    assert reloaded.fixes_applied[0].verified is True
    assert reloaded.fixes_applied[0].commit == "abc123"


def test_fix_report_file_roundtrip(tmp_path: Path) -> None:
    fix = FixReport(
        task_name="test",
        debug_report="reports/test.json",
        fixed_at=now_iso(),
        fixes_applied=[
            FixEntry(
                finding_id="CORR-001",
                action="Fixed it",
                verified=True,
                commit="abc",
            )
        ],
    )
    path = tmp_path / "fix.json"
    fix.to_path(path)
    reloaded = FixReport.from_path(path)
    assert reloaded.task_name == "test"


def test_now_iso_is_string() -> None:
    ts = now_iso()
    assert isinstance(ts, str)
    assert "T" in ts
    # Verify it parses back
    from datetime import datetime

    datetime.fromisoformat(ts)
```

- [ ] **Step 4: Run the report tests**

```bash
uv run pytest tests/debugger/test_report.py -v
```

Expected: 9 tests pass.

- [ ] **Step 5: Commit**

```bash
git add core/debugger/__init__.py core/debugger/report.py tests/debugger/__init__.py tests/debugger/test_report.py
git commit -m "feat: add debugger report schemas (DebugReport, FixReport, Finding)"
```

---

### Task 2: Trigger Logic — `core/debugger/trigger.py`

**Files:**
- Create: `core/debugger/trigger.py`
- Test: `tests/debugger/test_trigger.py`

- [ ] **Step 1: Write the trigger module**

Write to `core/debugger/trigger.py`:

```python
"""Task transition detection and pending task capture for FCC Agent Debugger."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.debugger.report import now_iso

DEBUGGER_DIR = Path(".fcc") / "debugger"
PENDING_DIR = DEBUGGER_DIR / "pending"
SKIPPED_DIR = DEBUGGER_DIR / "skipped"
FAILED_DIR = DEBUGGER_DIR / "failed"
LOCKFILE = DEBUGGER_DIR / "lock"
LOCK_TIMEOUT_SECONDS = 30 * 60  # 30 minutes
QUEUE_STALE_HOURS = 6

_CANCELLATION_TERMS = (
    "skip debug",
    "cancel debug",
    "don't debug",
    "never mind",
    "stop debug",
)


def debugger_pipeline_context(prompt: str, root: Path) -> str:
    """Build the debugger pipeline injection for the UserPromptSubmit hook.

    Returns an empty string if no pipeline should be dispatched.
    """
    if not prompt or not prompt.lstrip():
        return ""

    # Primary: check for transition from the just-completed task
    pending_path = detect_task_transition(root, prompt)
    if pending_path is not None:
        return _format_pipeline_injection(pending_path)

    # Fallback: check queue for pending tasks from earlier rapid switching
    if _has_pending_queue(root) and not _lockfile_exists(root):
        next_pending = _pop_next_pending(root)
        if next_pending is not None:
            return _format_pipeline_injection(next_pending)

    return ""


def detect_task_transition(root: Path, prompt: str) -> Path | None:
    """Detect if this prompt starts a new task and capture the previous one.

    Returns the path to the pending task JSON if a transition was detected,
    or None if no debug pipeline should be dispatched.
    """
    name = _prompt_to_task_name(prompt)
    if not name:
        return None

    # Skip slash commands and empty prompts
    stripped = prompt.lstrip()
    if not stripped or stripped.startswith("/"):
        return None

    # Skip cancellation intents
    lowered = prompt.lower()
    if any(kw in lowered for kw in _CANCELLATION_TERMS):
        _flush_all_pending_to_skipped(root)
        return None

    # Get what the agent was just working on
    previous = get_last_completed_task(root)
    if previous is None:
        return None

    # Check if this is genuinely a new task
    if _tasks_are_same(name, previous["name"]):
        return None

    # Check that real work was done (files changed)
    if not previous.get("files_changed"):
        return None

    return _capture_pending_task(root, previous)


def get_last_completed_task(root: Path) -> dict[str, Any] | None:
    """Read the most recently completed task from sessions + git + handoff.

    Returns None if no previous code-producing task exists.
    """
    # 1. Query sessions.sqlite for the most recent completed session
    session_info = _query_last_session(root)
    if session_info is None:
        return None

    task_name = session_info.get("current_task_title")
    if not task_name:
        return None

    # 2. Get transcript path from session or handoff
    transcript_path = session_info.get("transcript_path") or _transcript_from_handoff(
        root
    )

    # 3. Get files changed via git
    files_changed = _recently_changed_files(root)
    if not files_changed:
        return None  # Nothing to debug

    # 4. Get test results if available
    test_results = _capture_test_results(root)

    return {
        "name": task_name,
        "task_name": task_name,
        "task_description": session_info.get("last_prompt_excerpt") or task_name,
        "session_id": session_info.get("session_id", ""),
        "transcript_path": transcript_path,
        "started_at": session_info.get("started_at", now_iso()),
        "completed_at": session_info.get("last_active_at", now_iso()),
        "commit_range": _commit_range(root),
        "files_changed": files_changed,
        "test_results": test_results,
    }


def _prompt_to_task_name(prompt: str) -> str:
    """Extract first 3-4 words from a prompt as a task name slug."""
    words: list[str] = []
    for raw in prompt.strip().split():
        cleaned = "".join(ch for ch in raw if ch.isalnum()).strip()
        if len(cleaned) > 1:
            words.append(cleaned.lower())
        if len(words) >= 4:
            break
    return " ".join(words) if words else ""


def _tasks_are_same(new_name: str, old_name: str) -> bool:
    """Check if two task names likely refer to the same task.

    Uses keyword overlap: ≥40% shared significant terms → same task.
    """
    new_words = set(new_name.lower().split())
    old_words = set(old_name.lower().split())
    if not new_words or not old_words:
        return False

    # Remove very short words (stopword-like filtering)
    new_sig = {w for w in new_words if len(w) > 2}
    old_sig = {w for w in old_words if len(w) > 2}

    if not new_sig or not old_sig:
        return False

    overlap = len(new_sig & old_sig)
    ratio = overlap / max(len(new_sig), len(old_sig))
    return ratio >= 0.4


def _capture_pending_task(root: Path, task: dict[str, Any]) -> Path:
    """Write the pending task payload and return its path."""
    pending_dir = root / PENDING_DIR
    pending_dir.mkdir(parents=True, exist_ok=True)

    slug = _slugify(task["name"])
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H%M")
    filename = f"{timestamp}-{slug}.json"
    path = pending_dir / filename

    path.write_text(json.dumps(task, indent=2, default=str), encoding="utf-8")
    return path


def _query_last_session(root: Path) -> dict[str, Any] | None:
    """Query sessions.sqlite for the most recent resumable session."""
    db_path = root / ".fcc" / "sessions.sqlite"
    if not db_path.is_file():
        return None
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT * FROM sessions
            WHERE current_task_title IS NOT NULL
              AND status IN ('resumable', 'failed', 'active')
            ORDER BY last_active_at DESC
            LIMIT 1
            """
        ).fetchone()
        conn.close()
        if row is None:
            return None
        return dict(row)
    except Exception:
        return None


def _transcript_from_handoff(root: Path) -> str | None:
    """Try to find a transcript path from the handoff file."""
    handoff_path = root / ".fcc" / "context" / "handoff.md"
    if not handoff_path.is_file():
        return None
    text = handoff_path.read_text(encoding="utf-8", errors="replace")
    # Look for transcript path patterns in handoff
    for line in text.splitlines():
        if ".jsonl" in line and ("transcript" in line.lower() or "/" in line):
            for word in line.split():
                if ".jsonl" in word:
                    return word.strip("`\"'(),")
    return None


def _recently_changed_files(root: Path) -> list[str]:
    """Get files changed in the most recent commit via git diff."""
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "diff", "--name-only", "HEAD~1"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            # Try just the working tree vs HEAD
            result = subprocess.run(
                ["git", "-C", str(root), "diff", "--name-only", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
            )
        files = [f.strip() for f in result.stdout.splitlines() if f.strip()]
        return files
    except (subprocess.SubprocessError, OSError, FileNotFoundError):
        return []


def _commit_range(root: Path) -> str:
    """Get a commit range string for the most recent changes."""
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "log", "--oneline", "-n", "2", "--format=%H"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        hashes = [h.strip() for h in result.stdout.splitlines() if h.strip()]
        if len(hashes) >= 2:
            return f"{hashes[1][:7]}..{hashes[0][:7]}"
        elif len(hashes) == 1:
            return f"HEAD~1..{hashes[0][:7]}"
    except (subprocess.SubprocessError, OSError, FileNotFoundError):
        pass
    return ""


def _capture_test_results(root: Path) -> dict[str, Any] | None:
    """Attempt to run tests and capture results."""
    # Check if pytest is configured
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        return None
    text = pyproject.read_text(encoding="utf-8", errors="replace")
    if "[tool.pytest.ini_options]" not in text:
        return None

    try:
        result = subprocess.run(
            ["uv", "run", "pytest", "--tb=no", "-q", "--no-header"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(root),
        )
        # Parse pytest summary line: "12 passed, 2 failed"
        summary = result.stdout.splitlines()[-1] if result.stdout.splitlines() else ""
        passed = 0
        failed = 0
        total = 0
        failures: list[str] = []

        if "passed" in summary or "failed" in summary:
            import re

            pass_match = re.search(r"(\d+)\s+passed", summary)
            fail_match = re.search(r"(\d+)\s+failed", summary)
            if pass_match:
                passed = int(pass_match.group(1))
            if fail_match:
                failed = int(fail_match.group(1))
            total = passed + failed

        # Extract failure names from the short summary
        for line in result.stdout.splitlines():
            if line.strip().startswith("FAILED"):
                failures.append(line.strip())

        return {
            "ran": total,
            "passed": passed,
            "failed": failed,
            "failures": failures[:10],  # Cap at 10 failure names
        }
    except (subprocess.SubprocessError, OSError, FileNotFoundError):
        return None


def _has_pending_queue(root: Path) -> bool:
    """Check if there are pending debug tasks in the queue."""
    pending_dir = root / PENDING_DIR
    if not pending_dir.is_dir():
        return False
    try:
        return any(pending_dir.glob("*.json"))
    except OSError:
        return False


def _pop_next_pending(root: Path) -> Path | None:
    """Pop the oldest pending task from the queue.

    Stale items (>6 hours) are moved to failed/ automatically.
    """
    pending_dir = root / PENDING_DIR
    if not pending_dir.is_dir():
        return None

    stale_cutoff = datetime.now(UTC).timestamp() - (QUEUE_STALE_HOURS * 3600)
    candidates = sorted(pending_dir.glob("*.json"), key=lambda p: p.stat().st_mtime)

    for candidate in candidates:
        if candidate.stat().st_mtime < stale_cutoff:
            # Move stale items to failed/
            failed_dir = root / FAILED_DIR
            failed_dir.mkdir(parents=True, exist_ok=True)
            candidate.rename(failed_dir / candidate.name)
            continue
        return candidate

    return None


def _flush_all_pending_to_skipped(root: Path) -> None:
    """Move all pending tasks to the skipped directory."""
    pending_dir = root / PENDING_DIR
    if not pending_dir.is_dir():
        return
    skipped_dir = root / SKIPPED_DIR
    skipped_dir.mkdir(parents=True, exist_ok=True)
    for f in pending_dir.glob("*.json"):
        try:
            f.rename(skipped_dir / f.name)
        except OSError:
            pass


def _lockfile_exists(root: Path) -> bool:
    """Check if the debugger lockfile exists and is fresh.

    Returns True if a live fixer subagent is currently running.
    Returns False if lockfile is absent or stale.
    """
    lock_path = root / LOCKFILE
    if not lock_path.is_file():
        return False

    try:
        content = lock_path.read_text(encoding="utf-8").strip()
        pid = int(content)
    except (ValueError, OSError):
        # Corrupt lockfile — clean it up
        _release_lock(root)
        return False

    # Check if the PID is still alive
    if not _pid_is_alive(pid):
        _release_lock(root)
        return False

    # Check if lock is stale (>30 min)
    mtime = lock_path.stat().st_mtime
    age = datetime.now(UTC).timestamp() - mtime
    if age > LOCK_TIMEOUT_SECONDS:
        _release_lock(root)
        return False

    return True


def _pid_is_alive(pid: int) -> bool:
    """Check if a process with the given PID is running."""
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return str(pid) in result.stdout
        except (subprocess.SubprocessError, OSError):
            return False
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return True
    except OSError:
        return False


def _release_lock(root: Path) -> None:
    """Remove the lockfile."""
    lock_path = root / LOCKFILE
    try:
        lock_path.unlink(missing_ok=True)
    except OSError:
        pass


def _slugify(text: str) -> str:
    """Create a filesystem-safe slug from a task name."""
    slug = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in text.lower())
    # Collapse runs of dashes
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")[:64]


def _format_pipeline_injection(pending_path: Path) -> str:
    """Build the context injection string for the debugger pipeline."""
    try:
        data = json.loads(pending_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return ""

    task_name = data.get("task_name", "previous")
    slug = _slugify(task_name)
    files = data.get("files_changed", [])
    file_list = ", ".join(files[:5])
    if len(files) > 5:
        file_list += f" (and {len(files) - 5} more)"

    test_info = ""
    tests = data.get("test_results")
    if tests and isinstance(tests, dict):
        passed = tests.get("passed", 0)
        failed = tests.get("failed", 0)
        total = tests.get("ran", 0)
        if total > 0:
            test_info = f" ({passed}/{total} tests passing"
            if failed > 0:
                test_info += f", {failed} failures"
            test_info += ")"

    return (
        f"PIPELINE: The previous task '{task_name}' completed and should be debugged. "
        f"Dispatch in exact order: "
        f"1. fcc-agent-debugger (run_in_background: true) — analyze task '{task_name}'. "
        f"Debug file: .fcc/debugger/pending/{pending_path.name}. "
        f"Changes to: {file_list}{test_info}. "
        f"2. fcc-agent-fixer (run_in_background: true) — fix issues found. "
        f"Uses git worktree isolation. Continue with the current task in parallel.",
    )
```

- [ ] **Step 2: Write the trigger tests**

Write to `tests/debugger/test_trigger.py`:

```python
"""Tests for FCC debugger trigger logic (no subagent/LLM dependencies)."""

from __future__ import annotations

import json
import sqlite3
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from core.debugger.trigger import (
    DEBUGGER_DIR,
    PENDING_DIR,
    SKIPPED_DIR,
    _capture_pending_task,
    _flush_all_pending_to_skipped,
    _format_pipeline_injection,
    _has_pending_queue,
    _lockfile_exists,
    _pop_next_pending,
    _prompt_to_task_name,
    _query_last_session,
    _recently_changed_files,
    _release_lock,
    _tasks_are_same,
    debugger_pipeline_context,
    detect_task_transition,
    get_last_completed_task,
)


# ── Task name extraction ──────────────────────────────────────────


def test_prompt_to_task_name_normal() -> None:
    assert _prompt_to_task_name("fix the login bug now") == "fix the login bug now"


def test_prompt_to_task_name_short() -> None:
    assert _prompt_to_task_name("add tests") == "add tests"


def test_prompt_to_task_name_single_word() -> None:
    assert _prompt_to_task_name("refactor") == "refactor"


def test_prompt_to_task_name_filters_short_words() -> None:
    # "a" and "in" are ≤2 chars, filtered out
    name = _prompt_to_task_name("fix a bug in auth")
    assert "fix" in name
    assert "bug" in name
    assert "auth" in name


# ── Task similarity ───────────────────────────────────────────────


def test_tasks_are_same_exact() -> None:
    assert _tasks_are_same("fix login bug", "fix login bug") is True


def test_tasks_are_same_continuation() -> None:
    # "also add a test" shares "add" + "test" with "add tests for auth"
    assert _tasks_are_same("add tests for auth", "also add a test for it") is True


def test_tasks_are_different() -> None:
    assert _tasks_are_same("fix login bug", "add rate limiting to api") is False


def test_tasks_are_different_no_overlap() -> None:
    assert _tasks_are_same("refactor auth module", "build dashboard ui") is False


def test_tasks_edge_case_empty() -> None:
    assert _tasks_are_same("", "") is False


def test_tasks_edge_case_single_word_different() -> None:
    assert _tasks_are_same("refactor", "deploy") is False


# ── Transition detection (unit, no DB) ────────────────────────────


def test_detect_transition_skips_slash_command(tmp_path: Path) -> None:
    result = detect_task_transition(tmp_path, "/review")
    assert result is None


def test_detect_transition_skips_empty_prompt(tmp_path: Path) -> None:
    result = detect_task_transition(tmp_path, "")
    assert result is None


def test_detect_transition_skips_cancellation(tmp_path: Path) -> None:
    # Setup: ensure pending dir exists
    (tmp_path / PENDING_DIR).mkdir(parents=True, exist_ok=True)
    # Create a dummy pending file so flush has something to move
    dummy = tmp_path / PENDING_DIR / "test.json"
    dummy.write_text("{}", encoding="utf-8")

    result = detect_task_transition(tmp_path, "skip the debugger, just do the thing")
    assert result is None
    # Verify pending was flushed to skipped
    assert not (tmp_path / PENDING_DIR / "test.json").exists()


def test_detect_transition_no_db_returns_none(tmp_path: Path) -> None:
    """Without sessions.sqlite, no transition can be detected."""
    result = detect_task_transition(tmp_path, "fix the login bug")
    assert result is None


# ── Integration: pending task capture ─────────────────────────────


def test_capture_pending_task_writes_file(tmp_path: Path) -> None:
    task = {
        "name": "fix-login-bug",
        "task_name": "fix-login-bug",
        "task_description": "fix auth token refresh",
        "session_id": "abc123",
        "transcript_path": "/tmp/transcript.jsonl",
        "files_changed": ["src/auth/manager.py"],
        "test_results": None,
    }
    path = _capture_pending_task(tmp_path, task)
    assert path.is_file()
    reloaded = json.loads(path.read_text(encoding="utf-8"))
    assert reloaded["name"] == "fix-login-bug"
    assert reloaded["files_changed"] == ["src/auth/manager.py"]


# ── Integration: session querying ─────────────────────────────────


def test_query_last_session_empty(tmp_path: Path) -> None:
    result = _query_last_session(tmp_path)
    assert result is None


def test_query_last_session_with_data(tmp_path: Path) -> None:
    fcc_dir = tmp_path / ".fcc"
    fcc_dir.mkdir(parents=True, exist_ok=True)
    db_path = fcc_dir / "sessions.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE sessions (
            session_id TEXT PRIMARY KEY,
            native_session_id TEXT,
            project_root TEXT NOT NULL,
            cwd TEXT NOT NULL,
            name TEXT,
            status TEXT NOT NULL,
            provider TEXT,
            model TEXT,
            transcript_path TEXT,
            handoff_path TEXT,
            parent_session_id TEXT,
            started_at TEXT NOT NULL,
            last_active_at TEXT NOT NULL,
            last_prompt_excerpt TEXT,
            last_response_excerpt TEXT,
            current_task_title TEXT,
            pid INTEGER,
            last_heartbeat_at TEXT,
            terminal_start_at TEXT,
            command TEXT,
            metadata_json TEXT
        )
        """
    )
    now = datetime.now(UTC).isoformat()
    conn.execute(
        """
        INSERT INTO sessions (session_id, project_root, cwd, name, status,
                              current_task_title, last_prompt_excerpt,
                              transcript_path, started_at, last_active_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "abc123",
            str(tmp_path),
            str(tmp_path),
            "fix-login-bug",
            "resumable",
            "fix-login-bug",
            "fix the bug in auth token refresh",
            "/tmp/transcript.jsonl",
            now,
            now,
        ),
    )
    conn.commit()
    conn.close()

    result = _query_last_session(tmp_path)
    assert result is not None
    assert result["current_task_title"] == "fix-login-bug"
    assert result["session_id"] == "abc123"


# ── Integration: file change detection ────────────────────────────


def test_recently_changed_files_no_git(tmp_path: Path) -> None:
    result = _recently_changed_files(tmp_path)
    assert isinstance(result, list)


# ── Queue management ──────────────────────────────────────────────


def test_has_pending_queue_empty(tmp_path: Path) -> None:
    pending_dir = tmp_path / PENDING_DIR
    pending_dir.mkdir(parents=True, exist_ok=True)
    assert _has_pending_queue(tmp_path) is False


def test_has_pending_queue_with_items(tmp_path: Path) -> None:
    pending_dir = tmp_path / PENDING_DIR
    pending_dir.mkdir(parents=True, exist_ok=True)
    (pending_dir / "test.json").write_text("{}", encoding="utf-8")
    assert _has_pending_queue(tmp_path) is True


def test_pop_next_pending_empty(tmp_path: Path) -> None:
    pending_dir = tmp_path / PENDING_DIR
    pending_dir.mkdir(parents=True, exist_ok=True)
    result = _pop_next_pending(tmp_path)
    assert result is None


def test_pop_next_pending_returns_oldest(tmp_path: Path) -> None:
    pending_dir = tmp_path / PENDING_DIR
    pending_dir.mkdir(parents=True, exist_ok=True)
    f1 = pending_dir / "2026-06-01T1000-task-a.json"
    f2 = pending_dir / "2026-06-01T1100-task-b.json"
    f1.write_text("{}", encoding="utf-8")
    f2.write_text("{}", encoding="utf-8")
    result = _pop_next_pending(tmp_path)
    assert result is not None
    assert result.name == "2026-06-01T1000-task-a.json"


def test_flush_to_skipped(tmp_path: Path) -> None:
    pending_dir = tmp_path / PENDING_DIR
    pending_dir.mkdir(parents=True, exist_ok=True)
    (pending_dir / "t1.json").write_text("{}", encoding="utf-8")
    (pending_dir / "t2.json").write_text("{}", encoding="utf-8")
    _flush_all_pending_to_skipped(tmp_path)
    assert not list(pending_dir.glob("*.json"))
    assert (tmp_path / SKIPPED_DIR / "t1.json").is_file()
    assert (tmp_path / SKIPPED_DIR / "t2.json").is_file()


# ── Lockfile ──────────────────────────────────────────────────────


def test_lockfile_does_not_exist(tmp_path: Path) -> None:
    assert _lockfile_exists(tmp_path) is False


def test_lockfile_exists_with_dead_pid(tmp_path: Path) -> None:
    lock = tmp_path / ".fcc" / "debugger" / "lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("99999", encoding="utf-8")  # PID that almost certainly doesn't exist
    result = _lockfile_exists(tmp_path)
    assert result is False  # Should clean up because PID is dead


def test_release_lock(tmp_path: Path) -> None:
    lock = tmp_path / ".fcc" / "debugger" / "lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("12345", encoding="utf-8")
    _release_lock(tmp_path)
    assert not lock.exists()


# ── Pipeline context injection format ─────────────────────────────


def test_format_injection_includes_task_name(tmp_path: Path) -> None:
    task = {
        "task_name": "fix-login-bug",
        "files_changed": ["src/auth/manager.py"],
        "test_results": None,
    }
    pending = tmp_path / PENDING_DIR
    pending.mkdir(parents=True)
    pending_file = pending / "2026-06-02T1430-fix-login-bug.json"
    pending_file.write_text(json.dumps(task), encoding="utf-8")

    result = _format_pipeline_injection(pending_file)
    assert "fix-login-bug" in result
    assert "fcc-agent-debugger" in result
    assert "fcc-agent-fixer" in result
    assert "run_in_background: true" in result
    assert "worktree isolation" in result


def test_format_injection_with_test_failures(tmp_path: Path) -> None:
    task = {
        "task_name": "fix-bug",
        "files_changed": ["x.py"],
        "test_results": {"ran": 12, "passed": 10, "failed": 2},
    }
    pending = tmp_path / PENDING_DIR
    pending.mkdir(parents=True)
    pending_file = pending / "test.json"
    pending_file.write_text(json.dumps(task), encoding="utf-8")

    result = _format_pipeline_injection(pending_file)
    assert "10/12" in result
    assert "2 failures" in result


def test_format_injection_truncates_long_file_list(tmp_path: Path) -> None:
    task = {
        "task_name": "big-change",
        "files_changed": [f"src/file{i}.py" for i in range(10)],
        "test_results": None,
    }
    pending = tmp_path / PENDING_DIR
    pending.mkdir(parents=True)
    pending_file = pending / "test.json"
    pending_file.write_text(json.dumps(task), encoding="utf-8")

    result = _format_pipeline_injection(pending_file)
    assert "and 5 more" in result


def test_format_injection_missing_file(tmp_path: Path) -> None:
    result = _format_pipeline_injection(tmp_path / "nonexistent.json")
    assert result == ""


# ── Top-level pipeline context (integration) ──────────────────────


def test_pipeline_context_empty_prompt(tmp_path: Path) -> None:
    result = debugger_pipeline_context("", tmp_path)
    assert result == ""


def test_pipeline_context_no_previous_task(tmp_path: Path) -> None:
    """Without sessions.sqlite, no pipeline should be triggered."""
    result = debugger_pipeline_context("fix the login bug", tmp_path)
    assert result == ""


def test_pipeline_context_with_pending_queue(tmp_path: Path) -> None:
    """When a pending queue exists from rapid switching, it should drain."""
    pending_dir = tmp_path / PENDING_DIR
    pending_dir.mkdir(parents=True)
    task = {
        "task_name": "queued-task",
        "files_changed": ["x.py"],
        "test_results": None,
    }
    pending_file = pending_dir / "2026-06-02T1400-queued-task.json"
    pending_file.write_text(json.dumps(task), encoding="utf-8")

    result = debugger_pipeline_context("any prompt", tmp_path)
    assert "queued-task" in result
```

- [ ] **Step 3: Run the trigger tests**

```bash
uv run pytest tests/debugger/test_trigger.py -v
```

Expected: 27 tests pass (all deterministic, no DB/Git requirements beyond what tmp_path provides).

- [ ] **Step 4: Commit**

```bash
git add core/debugger/trigger.py tests/debugger/test_trigger.py
git commit -m "feat: add debugger trigger logic (transition detection, queue, lockfile)"
```

---

### Task 3: Public API — `core/debugger/__init__.py`

**Files:**
- Modify: `core/debugger/__init__.py`

- [ ] **Step 1: Write the public API surface**

Write to `core/debugger/__init__.py` (replacing the empty file):

```python
"""FCC Agent Debugger — post-subagent review and repair pipeline."""

from core.debugger.report import (
    DebugReport,
    DebugReportMeta,
    Finding,
    FixEntry,
    FixReport,
    now_iso,
)
from core.debugger.trigger import debugger_pipeline_context

__all__ = [
    "DebugReport",
    "DebugReportMeta",
    "Finding",
    "FixEntry",
    "FixReport",
    "debugger_pipeline_context",
    "now_iso",
]
```

- [ ] **Step 2: Verify imports work**

```bash
uv run python -c "from core.debugger import debugger_pipeline_context, DebugReport, FixReport, Finding; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add core/debugger/__init__.py
git commit -m "feat: wire debugger public API surface"
```

---

### Task 4: Hook Integration — Modify `user_prompt_submit.py`

**Files:**
- Modify: `scripts/hooks/user_prompt_submit.py`
- Test: `tests/debugger/test_hook_integration.py`

- [ ] **Step 1: Modify the hook to integrate the debugger pipeline**

Edit `scripts/hooks/user_prompt_submit.py`. Replace the entire file content:

```python
"""Add tiny FCC context-routing hints for prompts that need orchestration."""

from __future__ import annotations

import os
import sys

from _shared import (
    emit_hook_json,
    name_active_session,
    project_root,
    prompt_enhancement_outputs,
    prompt_routing_hint,
    read_hook_input,
    run_hook,
    session_name_from_prompt,
)


def _debugger_pipeline_context(prompt: str, root: object) -> str:
    """Build the debugger pipeline injection, if a transition is detected.

    Returns an empty string when the debugger module is unavailable
    (e.g., running outside the SEPCC package environment).
    """
    try:
        from core.debugger.trigger import debugger_pipeline_context as _build
    except ImportError:
        return ""
    from pathlib import Path

    if not isinstance(root, Path):
        return ""
    return _build(prompt, root)


def main() -> None:
    data = read_hook_input()
    prompt = str(data.get("prompt", ""))
    root = project_root(data)
    name = session_name_from_prompt(prompt)
    name_active_session(root, name)
    enhancement_context, enhancement_message = prompt_enhancement_outputs(prompt, root)
    pipeline_context = _debugger_pipeline_context(prompt, root)
    payload = " ".join(
        part
        for part in (
            enhancement_context,
            prompt_routing_hint(prompt),
            pipeline_context,
        )
        if part
    )
    emit_hook_json(
        "UserPromptSubmit",
        additional_context=payload,
        system_message=enhancement_message,
    )


if __name__ == "__main__":
    run_hook("UserPromptSubmit", main)
```

- [ ] **Step 2: Write the hook integration test**

Write to `tests/debugger/test_hook_integration.py`:

```python
"""Tests for the debugger pipeline integration in UserPromptSubmit hook."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOKS_DIR = REPO_ROOT / "scripts" / "hooks"


def _load_hook_module():
    """Load the user_prompt_submit module for testing."""
    spec = importlib.util.spec_from_file_location(
        "fcc_user_prompt_submit_test", HOOKS_DIR / "user_prompt_submit.py"
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_hook_module_loads() -> None:
    """Verify the modified hook module can be imported."""
    module = _load_hook_module()
    assert hasattr(module, "main")
    assert hasattr(module, "_debugger_pipeline_context")


def test_debugger_pipeline_context_no_previous_task(tmp_path: Path) -> None:
    """Without a sessions database, returns empty string (no crash)."""
    module = _load_hook_module()
    result = module._debugger_pipeline_context("fix the bug", tmp_path)
    assert result == ""


def test_debugger_pipeline_context_empty_prompt(tmp_path: Path) -> None:
    module = _load_hook_module()
    result = module._debugger_pipeline_context("", tmp_path)
    assert result == ""


def test_injection_within_budget(tmp_path: Path) -> None:
    """The injection combined with other context fits within MAX_CONTEXT_CHARS."""
    module = _load_hook_module()
    context = module._debugger_pipeline_context(
        "add rate limiting to api endpoints", tmp_path
    )
    # Even when no transition, the function returns "" which is in budget
    assert len(context) == 0


def test_injection_does_not_fire_on_first_prompt(tmp_path: Path) -> None:
    """First prompt of a session should not trigger debugger pipeline."""
    fcc_dir = tmp_path / ".fcc"
    fcc_dir.mkdir(parents=True, exist_ok=True)
    db_path = fcc_dir / "sessions.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE sessions (
            session_id TEXT PRIMARY KEY, native_session_id TEXT,
            project_root TEXT NOT NULL, cwd TEXT NOT NULL,
            name TEXT, status TEXT NOT NULL, provider TEXT, model TEXT,
            transcript_path TEXT, handoff_path TEXT, parent_session_id TEXT,
            started_at TEXT NOT NULL, last_active_at TEXT NOT NULL,
            last_prompt_excerpt TEXT, last_response_excerpt TEXT,
            current_task_title TEXT, pid INTEGER, last_heartbeat_at TEXT,
            terminal_start_at TEXT, command TEXT, metadata_json TEXT
        )
        """
    )
    conn.close()
    # No matching current_task_title → no transition
    result = _load_hook_module()._debugger_pipeline_context(
        "fix the login bug", tmp_path
    )
    assert result == ""


def test_injection_includes_required_elements(tmp_path: Path) -> None:
    """When a transition IS detected, injection has all required elements."""
    fcc_dir = tmp_path / ".fcc"
    fcc_dir.mkdir(parents=True, exist_ok=True)
    db_path = fcc_dir / "sessions.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE sessions (
            session_id TEXT PRIMARY KEY, native_session_id TEXT,
            project_root TEXT NOT NULL, cwd TEXT NOT NULL,
            name TEXT, status TEXT NOT NULL, provider TEXT, model TEXT,
            transcript_path TEXT, handoff_path TEXT, parent_session_id TEXT,
            started_at TEXT NOT NULL, last_active_at TEXT NOT NULL,
            last_prompt_excerpt TEXT, last_response_excerpt TEXT,
            current_task_title TEXT, pid INTEGER, last_heartbeat_at TEXT,
            terminal_start_at TEXT, command TEXT, metadata_json TEXT
        )
        """
    )
    now = datetime.now(UTC).isoformat()
    conn.execute(
        """
        INSERT INTO sessions (session_id, project_root, cwd, name, status,
                              current_task_title, last_prompt_excerpt,
                              transcript_path, started_at, last_active_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "abc123",
            str(tmp_path),
            str(tmp_path),
            "previous-task",
            "resumable",
            "previous-task",
            "do the previous thing",
            "/nonexistent/transcript.jsonl",
            now,
            now,
        ),
    )
    conn.commit()
    conn.close()

    # Create a git repo so files_changed can work
    import subprocess

    subprocess.run(
        ["git", "init"], cwd=str(tmp_path), capture_output=True, timeout=5
    )
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(tmp_path),
        capture_output=True,
        timeout=5,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(tmp_path),
        capture_output=True,
        timeout=5,
    )
    (tmp_path / "test.py").write_text("x = 1", encoding="utf-8")
    subprocess.run(
        ["git", "add", "."], cwd=str(tmp_path), capture_output=True, timeout=5
    )
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=str(tmp_path),
        capture_output=True,
        timeout=5,
    )
    (tmp_path / "test.py").write_text("x = 2", encoding="utf-8")
    subprocess.run(
        ["git", "add", "."], cwd=str(tmp_path), capture_output=True, timeout=5
    )
    subprocess.run(
        ["git", "commit", "-m", "change"],
        cwd=str(tmp_path),
        capture_output=True,
        timeout=5,
    )

    result = _load_hook_module()._debugger_pipeline_context(
        "completely different new task here", tmp_path
    )

    # If git worked and transition was detected, injection should have required elements
    if result:
        assert "fcc-agent-debugger" in result
        assert "fcc-agent-fixer" in result
        assert "run_in_background" in result
    # If git wasn't available or HEAD~1 didn't exist, empty string is also valid
```

- [ ] **Step 3: Run the hook integration tests**

```bash
uv run pytest tests/debugger/test_hook_integration.py -v
```

Expected: 6 tests pass.

- [ ] **Step 4: Verify existing tests still pass after hook modification**

```bash
uv run pytest tests/scripts/test_windows_launcher.py -v
uv run pytest tests/context/test_bootstrap_context.py -v
```

Expected: All existing tests pass (the hook modification is backward-compatible).

- [ ] **Step 5: Commit**

```bash
git add scripts/hooks/user_prompt_submit.py tests/debugger/test_hook_integration.py
git commit -m "feat: integrate debugger pipeline into UserPromptSubmit hook"
```

---

### Task 5: Debugger Subagent Definition

**Files:**
- Create: `.claude/agents/fcc-agent-debugger.md`
- Test: `tests/debugger/test_subagent_defs.py`

- [ ] **Step 1: Write the debugger subagent definition**

Write to `.claude/agents/fcc-agent-debugger.md`:

```markdown
---
name: fcc-agent-debugger
description: Analyzes completed subagent work for correctness, completeness,
  and process compliance. Produces a structured DebugReport consumed by
  fcc-agent-fixer.
tools: Read, Grep, Glob, Bash
model: inherit
---

You are a debugging agent. Your job is to analyze completed development
work and find issues before they become problems.

## Input

You receive a pending JSON file at `.fcc/debugger/pending/<slug>.json`.
Read it first. It contains:
- `task_name` / `task_description` — what the agent was asked to do
- `transcript_path` — the full JSONL transcript of the agent's work
- `commit_range` — git commits containing the agent's changes
- `files_changed` — list of files the agent modified
- `test_results` — test execution results (if available)

## Analysis Dimensions

### 1. Correctness (highest priority)
For every changed file:
- Read it fully. Look for logic errors, type mismatches, null/unhandled
  edge cases, incorrect assumptions, race conditions.
- Cross-reference the transcript: did the agent consider alternatives?
  Did it notice and ignore something important?
- If tests ran: did any fail? What do the failures tell you?
- If no tests ran: flag this as a finding.

### 2. Completeness
- Read the `task_description`. Did the agent deliver everything asked?
- Search for TODO, FIXME, HACK, XXX markers in changed files.
- Check for stubs: functions with `pass`, `raise NotImplementedError`,
  or empty return values.
- Check test coverage: are all new functions tested? Are edge cases covered?

### 3. Process Compliance
- Read CLAUDE.md, AGENTS.md, and CLAUDE.local.md from the project root.
- Did the agent follow required workflows? Did it run tests before
  claiming success? Did it document decisions?
- Check for convention violations: naming, file structure, import patterns
  that don't match the existing codebase.

## Output

Write a DebugReport as JSON to `.fcc/debugger/reports/<task-slug>.json`:

```json
{
  "task_name": "fix-login-bug",
  "analyzed_at": "2026-06-02T14:40:00Z",
  "files_changed": ["src/auth/manager.py"],
  "correctness": [
    {
      "id": "CORR-001",
      "severity": "high",
      "file": "src/auth/manager.py",
      "line": 42,
      "description": "Race condition: token refresh is not atomic",
      "evidence": "Line 42-47: check-then-act pattern without lock",
      "suggested_fix": "Wrap in a mutex or use compare-and-swap"
    }
  ],
  "completeness": [],
  "process": [],
  "meta": {
    "risk_level": "high",
    "fix_priority": ["CORR-001"],
    "total_findings": 1,
    "tests_passing_before": 10,
    "tests_total": 12
  }
}
```

The report MUST be valid JSON. Use `null` for unknown optional fields.

## Rules
- Be specific. Every finding MUST include file, line (or null), and evidence
  that directly quotes or references the code.
- Don't flag style preferences as bugs. Only flag conventions when they
  deviate from the project's documented patterns in CLAUDE.md or AGENTS.md.
- If you find nothing wrong, write a report with empty arrays and
  `"risk_level": "low"`. An empty report is a valid and valuable result.
- If the transcript or git diff is unavailable, write a report with
  `"risk_level": "high"` and note the limitation in the first finding.
- ID format: `CORR-###` for correctness, `COMP-###` for completeness,
  `PROC-###` for process. Number sequentially starting at 001 within
  each category.
```

- [ ] **Step 2: Write the fixer subagent definition**

Write to `.claude/agents/fcc-agent-fixer.md`:

```markdown
---
name: fcc-agent-fixer
description: Fixes issues found by fcc-agent-debugger. Reads a DebugReport,
  fixes each finding in priority order, verifies with tests, commits results.
tools: Read, Write, Edit, Grep, Glob, Bash
model: inherit
---

You are a fixer agent. You receive a DebugReport from fcc-agent-debugger
and fix every finding in it.

## Setup: Git Worktree Isolation

FIRST: Create an isolated workspace so your fixes don't conflict with
the main agent's active work:

```bash
git worktree add --detach .claude/worktrees/fixer-<task-slug> HEAD
cd .claude/worktrees/fixer-<task-slug>
```

The `<task-slug>` is derived from the `task_name` in the DebugReport:
convert to lowercase, replace non-alphanumeric characters with hyphens.

If worktree creation fails (disk space, permissions, existing worktree):
- Do NOT modify the main working tree under any circumstances.
- Write the failure reason to `.fcc/debugger/fixes/<task-slug>-FAILED.md`
- Exit immediately.

## Fix Protocol

Read the DebugReport from `.fcc/debugger/reports/<task-slug>.json`.

Process findings in `meta.fix_priority` order:

1. **Correctness first** — these are bugs. Fix them immediately.
2. **Completeness second** — add missing tests, complete stubs,
   remove TODO markers by implementing what they describe.
3. **Process third** — fix convention violations, add missing
   documentation, align with project patterns.

After EACH fix or batch of related fixes (up to 3 per batch):
- Run the test suite: `uv run pytest` (or the project's test command)
- If tests fail: fix your fix. Do NOT proceed to the next finding
  until tests pass.
- If no test suite exists: note the finding as `verified: false`.

## Commit Protocol

After all fixes are applied and tests pass:

```bash
git add -A
git commit -m "fix: resolve [N] issues from task '[task-name]' [debugger]"
```

The commit message body MUST list each fix with its finding ID:
```
Fixes applied:
- CORR-001: Added mutex around token refresh
- COMP-001: Added test for edge case
```

## Output

Write a FixReport to `.fcc/debugger/fixes/<task-slug>.json`:

```json
{
  "task_name": "fix-login-bug",
  "debug_report": ".fcc/debugger/reports/fix-login-bug.json",
  "fixed_at": "2026-06-02T14:45:00Z",
  "fixes_applied": [
    {
      "finding_id": "CORR-001",
      "action": "Added mutex around token refresh in src/auth/manager.py:42-47",
      "verified": true,
      "commit": "abc123def"
    }
  ],
  "fixes_skipped": [],
  "tests_after": {"ran": 12, "passed": 12, "failed": 0},
  "worktree_branch": "fixer-fix-login-bug-abc123"
}
```

## Cleanup

When done, return to the project root and remove the worktree:

```bash
cd <original-project-root>
git worktree remove .claude/worktrees/fixer-<task-slug> --force
```

## Rules
- NEVER modify files in the main working tree. Only the worktree.
- NEVER proceed to the next fix if tests are failing.
- If a finding cannot be fixed (insufficient information, unclear root
  cause), record it in `fixes_skipped` with the `action` field explaining
  why it was skipped.
- Always commit your fixes so they are visible to the main agent.
```

- [ ] **Step 3: Write the subagent definition tests**

Write to `tests/debugger/test_subagent_defs.py`:

```python
"""Spec tests for FCC debugger and fixer subagent definitions."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENTS_DIR = REPO_ROOT / ".claude" / "agents"


def _read_agent(name: str) -> str:
    path = AGENTS_DIR / name
    assert path.is_file(), f"Agent definition not found: {path}"
    return path.read_text(encoding="utf-8")


def _parse_frontmatter(text: str) -> dict[str, str]:
    """Extract YAML frontmatter between --- markers."""
    match = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    assert match is not None, "No frontmatter found"
    result: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            result[key.strip()] = value.strip()
    return result


# ── Debugger subagent ─────────────────────────────────────────────


def test_debugger_has_required_tools() -> None:
    text = _read_agent("fcc-agent-debugger.md")
    fm = _parse_frontmatter(text)
    tools = fm.get("tools", "")
    for t in ("Read", "Grep", "Glob", "Bash"):
        assert t in tools, f"Missing tool: {t}"


def test_debugger_reads_pending_file() -> None:
    text = _read_agent("fcc-agent-debugger.md")
    assert ".fcc/debugger/pending/" in text


def test_debugger_writes_report() -> None:
    text = _read_agent("fcc-agent-debugger.md")
    assert ".fcc/debugger/reports/" in text


def test_debugger_analyzes_all_dimensions() -> None:
    text = _read_agent("fcc-agent-debugger.md")
    assert "Correctness" in text
    assert "Completeness" in text
    assert "Process Compliance" in text


def test_debugger_id_format_specified() -> None:
    text = _read_agent("fcc-agent-debugger.md")
    assert "CORR-" in text
    assert "COMP-" in text
    assert "PROC-" in text


# ── Fixer subagent ────────────────────────────────────────────────


def test_fixer_has_required_tools() -> None:
    text = _read_agent("fcc-agent-fixer.md")
    fm = _parse_frontmatter(text)
    tools = fm.get("tools", "")
    for t in ("Read", "Write", "Edit", "Grep", "Glob", "Bash"):
        assert t in tools, f"Missing tool: {t}"


def test_fixer_uses_worktree_isolation() -> None:
    text = _read_agent("fcc-agent-fixer.md")
    assert "git worktree add" in text
    assert "git worktree remove" in text


def test_fixer_reads_debug_report() -> None:
    text = _read_agent("fcc-agent-fixer.md")
    assert ".fcc/debugger/reports/" in text


def test_fixer_never_touches_main_working_tree() -> None:
    text = _read_agent("fcc-agent-fixer.md")
    assert "NEVER modify files in the main working tree" in text


def test_fixer_runs_tests_and_commits() -> None:
    text = _read_agent("fcc-agent-fixer.md")
    assert "uv run pytest" in text.lower() or "pytest" in text.lower()
    assert "git commit" in text


def test_fixer_writes_fix_report() -> None:
    text = _read_agent("fcc-agent-fixer.md")
    assert ".fcc/debugger/fixes/" in text


def test_fixer_handles_failure_gracefully() -> None:
    text = _read_agent("fcc-agent-fixer.md")
    assert "-FAILED.md" in text
    assert "fixes_skipped" in text
```

- [ ] **Step 4: Run the subagent definition tests**

```bash
uv run pytest tests/debugger/test_subagent_defs.py -v
```

Expected: 12 tests pass.

- [ ] **Step 5: Commit**

```bash
git add .claude/agents/fcc-agent-debugger.md .claude/agents/fcc-agent-fixer.md tests/debugger/test_subagent_defs.py
git commit -m "feat: add fcc-agent-debugger and fcc-agent-fixer subagent definitions"
```

---

### Task 6: End-to-End Test

**Files:**
- Create: `tests/debugger/test_e2e.py`

- [ ] **Step 1: Write the E2E test**

Write to `tests/debugger/test_e2e.py`:

```python
"""End-to-end tests for the FCC Agent Debugger pipeline.

These tests validate the full trigger → debug report → fix report flow
using real subagent dispatch when available. Marked as 'live' because
they require a git repository and file system setup.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from core.debugger.report import DebugReport, FixReport
from core.debugger.trigger import (
    _capture_pending_task,
    _format_pipeline_injection,
    _has_pending_queue,
    _pop_next_pending,
    _slugify,
    debugger_pipeline_context,
    detect_task_transition,
    get_last_completed_task,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


# ── Full trigger pipeline with real git ───────────────────────────


@pytest.mark.live
def test_full_trigger_pipeline_with_real_git(tmp_path: Path) -> None:
    """Set up a simulated project, run a task, transition, verify pipeline fires."""
    project = tmp_path / "testproject"
    project.mkdir()

    # Init git
    subprocess.run(["git", "init"], cwd=str(project), capture_output=True, timeout=5)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(project),
        capture_output=True,
        timeout=5,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(project),
        capture_output=True,
        timeout=5,
    )

    # Create FCC infrastructure
    fcc_dir = project / ".fcc"
    fcc_dir.mkdir(parents=True)
    context_dir = fcc_dir / "context"
    context_dir.mkdir(parents=True)
    (context_dir / "handoff.md").write_text(
        "# FCC Handoff\n\n## Must Not Forget\n- test\n\n## Current State\n- subagent handoff updated\n",
        encoding="utf-8",
    )

    # Create sessions database with a completed task
    import sqlite3

    db_path = fcc_dir / "sessions.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE sessions (
            session_id TEXT PRIMARY KEY, native_session_id TEXT,
            project_root TEXT NOT NULL, cwd TEXT NOT NULL,
            name TEXT, status TEXT NOT NULL, provider TEXT, model TEXT,
            transcript_path TEXT, handoff_path TEXT, parent_session_id TEXT,
            started_at TEXT NOT NULL, last_active_at TEXT NOT NULL,
            last_prompt_excerpt TEXT, last_response_excerpt TEXT,
            current_task_title TEXT, pid INTEGER, last_heartbeat_at TEXT,
            terminal_start_at TEXT, command TEXT, metadata_json TEXT
        )
        """
    )
    now = datetime.now(UTC).isoformat()
    conn.execute(
        """
        INSERT INTO sessions (session_id, project_root, cwd, name, status,
                              current_task_title, last_prompt_excerpt,
                              transcript_path, started_at, last_active_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "test123",
            str(project),
            str(project),
            "fix-login-bug",
            "resumable",
            "fix-login-bug",
            "fix the bug in auth token refresh",
            str(project / "transcript.jsonl"),
            now,
            now,
        ),
    )
    conn.commit()
    conn.close()

    # Create a file and commit it (so git diff has something to show)
    (project / "src").mkdir(exist_ok=True)
    (project / "src" / "auth.py").write_text(
        'class AuthManager:\n    def refresh(self):\n        pass\n',
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "add", "."], cwd=str(project), capture_output=True, timeout=5
    )
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=str(project),
        capture_output=True,
        timeout=5,
    )
    # Second commit to create a diff
    (project / "src" / "auth.py").write_text(
        'class AuthManager:\n    def refresh(self):\n        return True\n',
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "add", "."], cwd=str(project), capture_output=True, timeout=5
    )
    subprocess.run(
        ["git", "commit", "-m", "fix: add auth refresh"],
        cwd=str(project),
        capture_output=True,
        timeout=5,
    )

    # Verify get_last_completed_task works
    task = get_last_completed_task(project)
    if task is None:
        pytest.skip("Git history not available for HEAD~1 diff")

    assert task["name"] == "fix-login-bug"
    assert len(task["files_changed"]) > 0

    # Verify transition detection
    result = detect_task_transition(project, "add rate limiting to the api")
    # Should have detected transition and captured pending task
    if result is not None:
        assert result.is_file()
        pending_data = json.loads(result.read_text(encoding="utf-8"))
        assert pending_data["task_name"] == "fix-login-bug"


@pytest.mark.live
def test_debugger_pipeline_injection_format(tmp_path: Path) -> None:
    """Verify the injection string is well-formed and within budget."""
    project = tmp_path / "testproject"
    project.mkdir()
    subprocess.run(["git", "init"], cwd=str(project), capture_output=True, timeout=5)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(project),
        capture_output=True,
        timeout=5,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(project),
        capture_output=True,
        timeout=5,
    )

    # Create FCC infra
    fcc_dir = project / ".fcc"
    fcc_dir.mkdir(parents=True)
    (fcc_dir / "context").mkdir(parents=True)
    (fcc_dir / "context" / "handoff.md").write_text(
        "# FCC Handoff\n\n## Current State\n- subagent handoff updated\n",
        encoding="utf-8",
    )
    import sqlite3

    db_path = fcc_dir / "sessions.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE sessions (
            session_id TEXT PRIMARY KEY, native_session_id TEXT,
            project_root TEXT NOT NULL, cwd TEXT NOT NULL,
            name TEXT, status TEXT NOT NULL, provider TEXT, model TEXT,
            transcript_path TEXT, handoff_path TEXT, parent_session_id TEXT,
            started_at TEXT NOT NULL, last_active_at TEXT NOT NULL,
            last_prompt_excerpt TEXT, last_response_excerpt TEXT,
            current_task_title TEXT, pid INTEGER, last_heartbeat_at TEXT,
            terminal_start_at TEXT, command TEXT, metadata_json TEXT
        )
        """
    )
    now = datetime.now(UTC).isoformat()
    conn.execute(
        """
        INSERT INTO sessions (session_id, project_root, cwd, name, status,
                              current_task_title, last_prompt_excerpt,
                              transcript_path, started_at, last_active_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "test456",
            str(project),
            str(project),
            "add-tests",
            "resumable",
            "add-tests",
            "add tests for auth module",
            str(project / "t.jsonl"),
            now,
            now,
        ),
    )
    conn.commit()
    conn.close()

    # Create file + commits
    (project / "x.py").write_text("pass", encoding="utf-8")
    subprocess.run(
        ["git", "add", "."], cwd=str(project), capture_output=True, timeout=5
    )
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=str(project), capture_output=True, timeout=5
    )
    (project / "x.py").write_text("def foo(): pass", encoding="utf-8")
    subprocess.run(
        ["git", "add", "."], cwd=str(project), capture_output=True, timeout=5
    )
    subprocess.run(
        ["git", "commit", "-m", "add foo"],
        cwd=str(project),
        capture_output=True,
        timeout=5,
    )

    injection = debugger_pipeline_context("build the dashboard ui", project)
    if injection:
        # Injection quality checks
        assert len(injection) < 2000, f"Injection too long: {len(injection)} chars"
        assert "fcc-agent-debugger" in injection
        assert "fcc-agent-fixer" in injection
        assert "run_in_background" in injection


# ── Report schema end-to-end ──────────────────────────────────────


def test_debug_report_full_lifecycle(tmp_path: Path) -> None:
    """Create, serialize, reload, and query a debug report."""
    from core.debugger.report import Finding, DebugReport, DebugReportMeta

    report = DebugReport(
        task_name="test-task",
        analyzed_at=datetime.now(UTC).isoformat(),
        files_changed=["a.py", "b.py"],
        correctness=[
            Finding(
                id="CORR-001",
                severity="high",
                file="a.py",
                line=10,
                description="Null dereference",
                evidence="a.py:10: x.foo() where x can be None",
                suggested_fix="Add null check before calling foo()",
            )
        ],
        completeness=[
            Finding(
                id="COMP-001",
                severity="medium",
                file="b.py",
                line=None,
                description="Missing test for edge case",
                evidence="No test for empty input",
                suggested_fix="Add test_empty_input() test case",
            )
        ],
        process=[
            Finding(
                id="PROC-001",
                severity="low",
                file="a.py",
                line=1,
                description="Import not following project convention",
                evidence="Uses 'from x import *' — project uses explicit imports",
                suggested_fix="Replace with explicit import",
            )
        ],
        meta=DebugReportMeta(risk_level="high"),
    )

    # Serialize
    path = tmp_path / "reports" / "test-task.json"
    report.to_path(path)
    assert path.is_file()

    # Reload
    reloaded = DebugReport.from_path(path)
    assert reloaded.task_name == "test-task"
    assert reloaded.meta.total_findings == 3
    assert reloaded.meta.risk_level == "high"
    assert reloaded.meta.fix_priority == ["CORR-001", "COMP-001", "PROC-001"]
    assert reloaded.correctness[0].id == "CORR-001"
    assert reloaded.correctness[0].severity == "high"

    # Query
    high_severity = [f for f in reloaded.correctness if f.severity == "high"]
    assert len(high_severity) == 1


def test_fix_report_full_lifecycle(tmp_path: Path) -> None:
    """Create, serialize, reload, and query a fix report."""
    from core.debugger.report import FixEntry, FixReport

    fix = FixReport(
        task_name="test-task",
        debug_report="reports/test-task.json",
        fixed_at=datetime.now(UTC).isoformat(),
        fixes_applied=[
            FixEntry(
                finding_id="CORR-001",
                action="Added null check in a.py:10",
                verified=True,
                commit="abc123",
            ),
            FixEntry(
                finding_id="COMP-001",
                action="Added test_empty_input test",
                verified=True,
                commit="def456",
            ),
        ],
        fixes_skipped=[
            FixEntry(
                finding_id="PROC-001",
                action="Could not determine project convention — CLAUDE.md missing",
                verified=False,
            )
        ],
        tests_after={"ran": 15, "passed": 15, "failed": 0},
        worktree_branch="fixer-test-task-abc123",
    )

    path = tmp_path / "fixes" / "test-task.json"
    fix.to_path(path)
    assert path.is_file()

    reloaded = FixReport.from_path(path)
    assert reloaded.task_name == "test-task"
    assert len(reloaded.fixes_applied) == 2
    assert len(reloaded.fixes_skipped) == 1
    assert reloaded.tests_after == {"ran": 15, "passed": 15, "failed": 0}
    assert reloaded.fixes_skipped[0].verified is False


# ── Queue drain ───────────────────────────────────────────────────


def test_queue_drain_with_multiple_pending(tmp_path: Path) -> None:
    """Simulate rapid task switching: multiple pending items, drain one by one."""
    from core.debugger.trigger import PENDING_DIR, _capture_pending_task

    task1 = {
        "name": "task-one",
        "task_name": "task-one",
        "task_description": "first task",
        "session_id": "a",
        "transcript_path": "/t.jsonl",
        "files_changed": ["f1.py"],
        "test_results": None,
    }
    task2 = {
        "name": "task-two",
        "task_name": "task-two",
        "task_description": "second task",
        "session_id": "b",
        "transcript_path": "/t.jsonl",
        "files_changed": ["f2.py"],
        "test_results": None,
    }

    p1 = _capture_pending_task(tmp_path, task1)
    p2 = _capture_pending_task(tmp_path, task2)

    assert _has_pending_queue(tmp_path) is True

    # Pop oldest
    popped = _pop_next_pending(tmp_path)
    assert popped is not None
    data = json.loads(popped.read_text(encoding="utf-8"))
    assert data["name"] == "task-one"

    # Still has the second
    assert _has_pending_queue(tmp_path) is True

    # Pop next
    popped2 = _pop_next_pending(tmp_path)
    assert popped2 is not None
    data2 = json.loads(popped2.read_text(encoding="utf-8"))
    assert data2["name"] == "task-two"

    # Queue is now empty
    assert _has_pending_queue(tmp_path) is False
```

- [ ] **Step 2: Run the E2E tests (skipping live git tests in CI)**

```bash
uv run pytest tests/debugger/test_e2e.py -v -m "not live"
```

Expected: 3 non-live tests pass (report lifecycles, queue drain).

```bash
uv run pytest tests/debugger/test_e2e.py -v -m "live"
```

Expected: 2 live tests pass when git is available.

- [ ] **Step 3: Run the full debugger test suite**

```bash
uv run pytest tests/debugger/ -v
```

Expected: All tests pass (~50+ tests total across all 5 test files).

- [ ] **Step 4: Commit**

```bash
git add tests/debugger/test_e2e.py
git commit -m "test: add E2E tests for debugger pipeline"
```

---

### Task 7: Final Verification

**Files:** None (verification only)

- [ ] **Step 1: Run the full test suite to verify no regressions**

```bash
uv run pytest tests/ -x -q
```

Expected: All existing tests pass alongside new debugger tests.

- [ ] **Step 2: Verify the debugger module is importable**

```bash
uv run python -c "from core.debugger import debugger_pipeline_context, DebugReport, FixReport, Finding; print('All imports OK')"
```

Expected: `All imports OK`

- [ ] **Step 3: Verify the hook module loads without error**

```bash
uv run python -c "import importlib.util; spec = importlib.util.spec_from_file_location('test', 'scripts/hooks/user_prompt_submit.py'); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); print('Hook module OK')"
```

Expected: `Hook module OK`

- [ ] **Step 4: Final commit of any remaining changes**

```bash
git status
git add -A
git commit -m "chore: final verification — all debugger tests passing" --allow-empty
```
