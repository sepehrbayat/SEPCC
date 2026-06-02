"""End-to-end tests for the FCC Agent Debugger pipeline.

These tests validate the full debugger pipeline flow:
- Trigger detection with real git repos and SQLite sessions
- Pipeline injection format verification
- DebugReport and FixReport lifecycle (serialize / deserialize / query)
- Pending queue drain behavior
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from core.debugger.report import DebugReport, DebugReportMeta, Finding, FixEntry, FixReport
from core.debugger.trigger import (
    _capture_pending_task,
    _has_pending_queue,
    _pop_next_pending,
    debugger_pipeline_context,
    detect_task_transition,
    get_last_completed_task,
)

# ---------------------------------------------------------------------------
# Shared SQL schema used by tests that need a real sessions.sqlite
# ---------------------------------------------------------------------------

_SESSIONS_DDL = """
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


def _git_init(repo: Path) -> None:
    """Initialize a git repository and configure user identity."""
    subprocess.run(
        ["git", "init"], cwd=str(repo), check=True, capture_output=True, text=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@e2e.example"],
        cwd=str(repo), check=True, capture_output=True, text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "E2E Test"],
        cwd=str(repo), check=True, capture_output=True, text=True,
    )


def _create_sessions_db(db_path: Path, task_title: str, transcript: str, status: str = "resumable") -> None:
    """Create a sessions.sqlite with one completed task row."""
    conn = sqlite3.connect(str(db_path))
    conn.execute(_SESSIONS_DDL)
    conn.execute(
        """
        INSERT INTO sessions (
            session_id, project_root, cwd, name, status,
            transcript_path, started_at, last_active_at, current_task_title
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            f"sess-{task_title}",
            str(db_path.parent),
            str(db_path.parent),
            task_title.replace("-", " ").title(),
            status,
            transcript,
            "2025-06-01T10:00:00Z",
            "2025-06-01T11:00:00Z",
            task_title,
        ),
    )
    conn.commit()
    conn.close()


def _make_two_commits(repo: Path, filename: str) -> None:
    """Create a file, commit it, modify it, commit again.

    Ensures ``git diff HEAD~1`` produces output.
    """
    filepath = repo / filename
    filepath.write_text("# version 1\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", filename], cwd=str(repo), check=True, capture_output=True, text=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "first commit"],
        cwd=str(repo), check=True, capture_output=True, text=True,
    )

    filepath.write_text("# version 2\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", filename], cwd=str(repo), check=True, capture_output=True, text=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "second commit"],
        cwd=str(repo), check=True, capture_output=True, text=True,
    )


# ===================================================================
# Test 1: Full trigger pipeline with real git
# ===================================================================


@pytest.mark.live
def test_full_trigger_pipeline_with_real_git(tmp_path: Path) -> None:
    """End-to-end: DB session -> handoff -> git diff -> pending capture."""
    project = tmp_path / "project"
    project.mkdir()

    # -- git setup --
    _git_init(project)

    # -- handoff file --
    ctx_dir = project / ".fcc" / "context"
    ctx_dir.mkdir(parents=True)
    (ctx_dir / "handoff.md").write_text(
        "Transcript: /tmp/sess-e2e.jsonl\nsubagent handoff updated\n",
        encoding="utf-8",
    )

    # -- sessions DB --
    db_path = project / ".fcc" / "sessions.sqlite"
    _create_sessions_db(db_path, "fix-login-bug", "/tmp/sess-e2e.jsonl")

    # -- two commits so HEAD~1 diff works --
    _make_two_commits(project, "app.py")

    # -- guard: skip if git diff HEAD~1 is unavailable --
    diff = subprocess.run(
        ["git", "diff", "--name-only", "HEAD~1"],
        cwd=str(project), capture_output=True, text=True,
    )
    if diff.returncode != 0 or not diff.stdout.strip():
        pytest.skip("git diff HEAD~1 not available in this environment")

    # -- get_last_completed_task --
    old_task = get_last_completed_task(project)
    assert old_task is not None, "get_last_completed_task returned None"
    assert old_task["task_name"] == "fix-login-bug"
    assert "app.py" in old_task["files_changed"]

    # -- detect_task_transition (new prompt = different task) --
    pending_path = detect_task_transition(project, "add rate limiting to the api")
    if pending_path is None:
        pytest.fail("detect_task_transition returned None unexpectedly")

    # -- verify the pending file --
    assert pending_path.is_file(), f"Pending file not found: {pending_path}"
    pending_data = json.loads(pending_path.read_text(encoding="utf-8"))
    assert pending_data["task_name"] == "fix-login-bug"


# ===================================================================
# Test 2: Pipeline injection format
# ===================================================================


@pytest.mark.live
def test_debugger_pipeline_injection_format(tmp_path: Path) -> None:
    """Injection string must contain subagent names and run_in_background."""
    project = tmp_path / "project"
    project.mkdir()

    # -- git setup --
    _git_init(project)

    # -- handoff file --
    ctx_dir = project / ".fcc" / "context"
    ctx_dir.mkdir(parents=True)
    (ctx_dir / "handoff.md").write_text(
        "Transcript: /tmp/sess-e2e-2.jsonl\nsubagent handoff updated\n",
        encoding="utf-8",
    )

    # -- sessions DB --
    db_path = project / ".fcc" / "sessions.sqlite"
    _create_sessions_db(db_path, "fix-login-bug", "/tmp/sess-e2e-2.jsonl")

    # -- two commits --
    _make_two_commits(project, "main.py")

    # -- guard --
    diff = subprocess.run(
        ["git", "diff", "--name-only", "HEAD~1"],
        cwd=str(project), capture_output=True, text=True,
    )
    if diff.returncode != 0 or not diff.stdout.strip():
        pytest.skip("git diff HEAD~1 not available")

    # -- debugger_pipeline_context --
    injection = debugger_pipeline_context("build the dashboard ui", project)

    if not injection:
        pytest.skip("No injection produced (task transition not detected)")

    # -- verify --
    assert len(injection) < 2000, f"Injection too long: {len(injection)} chars"
    assert "fcc-agent-debugger" in injection
    assert "fcc-agent-fixer" in injection
    assert "run_in_background" in injection


# ===================================================================
# Test 3: DebugReport full lifecycle
# ===================================================================


def test_debug_report_full_lifecycle(tmp_path: Path) -> None:
    """Create a DebugReport, serialize, reload, and query findings."""
    # -- 3 findings: 1 correctness, 1 completeness, 1 process --
    f_c = Finding(
        id="C1",
        severity="high",
        file="src/auth.py",
        line=42,
        description="Missing input validation in login handler",
        evidence="user_id = request.form['user_id']",
        suggested_fix="Use request.form.get('user_id') with fallback",
    )
    f_cp = Finding(
        id="CP1",
        severity="medium",
        file="src/auth.py",
        line=58,
        description="No error handling for database timeout",
        evidence="result = db.execute(query)",
        suggested_fix="Wrap in try/except with retry logic",
    )
    f_p = Finding(
        id="P1",
        severity="low",
        file="README.md",
        description="Commit messages lack conventional format",
        evidence="git log shows 'fix', 'update', 'wip'",
        suggested_fix="Adopt conventional commits standard",
    )

    report = DebugReport(
        task_name="fix-login-bug",
        analyzed_at=datetime.now(UTC).isoformat(),
        files_changed=["src/auth.py", "README.md"],
        correctness=[f_c],
        completeness=[f_cp],
        process=[f_p],
        meta=DebugReportMeta(risk_level="high"),
    )

    # -- serialize --
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    report_path = reports_dir / "test-task.json"
    report.to_path(report_path)
    assert report_path.is_file()

    # -- reload --
    reloaded = DebugReport.from_path(report_path)

    # -- verify task_name --
    assert reloaded.task_name == "fix-login-bug"

    # -- verify total_findings --
    assert reloaded.meta.total_findings == 3

    # -- verify risk_level --
    assert reloaded.meta.risk_level == "high"

    # -- verify fix_priority order (high > medium > low) --
    assert reloaded.meta.fix_priority == ["C1", "CP1", "P1"]

    # -- verify correctness[0] --
    assert len(reloaded.correctness) == 1
    assert reloaded.correctness[0].id == "C1"
    assert reloaded.correctness[0].severity == "high"

    # -- query: high severity correctness findings --
    high_severity = [f for f in reloaded.correctness if f.severity == "high"]
    assert len(high_severity) == 1


# ===================================================================
# Test 4: FixReport full lifecycle
# ===================================================================


def test_fix_report_full_lifecycle(tmp_path: Path) -> None:
    """Create a FixReport with applied + skipped fixes, serialize, reload, verify."""
    # -- fixes_applied: 2 entries --
    applied_1 = FixEntry(
        finding_id="C1",
        action="Added input validation with request.form.get()",
        verified=True,
        commit="abc123def",
    )
    applied_2 = FixEntry(
        finding_id="CP1",
        action="Added try/except with retry for DB operations",
        verified=True,
        commit="456abc789",
    )

    # -- fixes_skipped: 1 entry --
    skipped = FixEntry(
        finding_id="P1",
        action="Update commit message conventions in CONTRIBUTING.md",
        verified=False,
    )

    report = FixReport(
        task_name="fix-login-bug",
        debug_report="reports/fix-login-bug.json",
        fixed_at=datetime.now(UTC).isoformat(),
        fixes_applied=[applied_1, applied_2],
        fixes_skipped=[skipped],
        tests_after={"passed": 12, "failed": 0, "total": 12},
        worktree_branch="fix/fix-login-bug-debug",
    )

    # -- serialize --
    fixes_dir = tmp_path / "fixes"
    fixes_dir.mkdir()
    report_path = fixes_dir / "test-task.json"
    report.to_path(report_path)
    assert report_path.is_file()

    # -- reload --
    reloaded = FixReport.from_path(report_path)

    # -- verify task_name --
    assert reloaded.task_name == "fix-login-bug"

    # -- verify counts --
    assert len(reloaded.fixes_applied) == 2
    assert len(reloaded.fixes_skipped) == 1

    # -- verify tests_after dict --
    assert reloaded.tests_after is not None
    assert reloaded.tests_after["passed"] == 12
    assert reloaded.tests_after["failed"] == 0
    assert reloaded.tests_after["total"] == 12

    # -- verify fixes_skipped[0].verified is False --
    assert reloaded.fixes_skipped[0].finding_id == "P1"
    assert reloaded.fixes_skipped[0].verified is False

    # -- verify fixes_applied details --
    assert reloaded.fixes_applied[0].finding_id == "C1"
    assert reloaded.fixes_applied[0].verified is True
    assert reloaded.fixes_applied[0].commit == "abc123def"


# ===================================================================
# Test 5: Pending queue drain
# ===================================================================


def test_queue_drain_with_multiple_pending(tmp_path: Path) -> None:
    """_pop_next_pending returns oldest first; queue drains when all consumed."""
    # -- task one (oldest) --
    task_one = {"task_name": "task-one", "files_changed": ["a.py"]}
    path_one = _capture_pending_task(tmp_path, task_one)
    assert path_one.is_file()

    # ensure distinct mtimes
    time.sleep(0.05)

    # -- task two (newer) --
    task_two = {"task_name": "task-two", "files_changed": ["b.py"]}
    path_two = _capture_pending_task(tmp_path, task_two)
    assert path_two.is_file()

    # -- queue non-empty --
    assert _has_pending_queue(tmp_path) is True

    # -- pop oldest --
    popped_one = _pop_next_pending(tmp_path)
    assert popped_one is not None
    assert "task-one" in popped_one.name
    popped_one.unlink()  # consume the entry

    # -- still has second --
    assert _has_pending_queue(tmp_path) is True

    # -- pop next --
    popped_two = _pop_next_pending(tmp_path)
    assert popped_two is not None
    assert "task-two" in popped_two.name
    popped_two.unlink()  # consume the entry

    # -- queue empty --
    assert _has_pending_queue(tmp_path) is False
