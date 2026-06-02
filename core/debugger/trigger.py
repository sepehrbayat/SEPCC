"""Deterministic task-transition detection and pending-task capture for the FCC Agent Debugger.

This module runs inside hooks -- it must be deterministic, fast (<500ms), and never
call an LLM.  It reads from sessions.sqlite, handoff.md, and git.  All paths are
relative to *root*.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from core.debugger.report import now_iso

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEBUGGER_DIR = Path(".fcc") / "debugger"
PENDING_DIR = DEBUGGER_DIR / "pending"
SKIPPED_DIR = DEBUGGER_DIR / "skipped"
FAILED_DIR = DEBUGGER_DIR / "failed"
LOCKFILE = DEBUGGER_DIR / "lock"

LOCK_TIMEOUT_SECONDS = 30 * 60  # 30 minutes
QUEUE_STALE_HOURS = 6

_CANCELLATION_TERMS: tuple[str, ...] = (
    "cancel",
    "stop",
    "abort",
    "nevermind",
    "never mind",
    "scratch that",
    "forget it",
)


# ===================================================================
# Public entry point
# ===================================================================


def debugger_pipeline_context(prompt: str, root: Path) -> str:
    """Entry point called from the hook.

    Returns an empty string when no pipeline injection is needed.  Primary path
    checks for a task transition via ``detect_task_transition()``.  Fallback
    checks the pending queue via ``_has_pending_queue()`` and
    ``_pop_next_pending()``.

    Returns the formatted injection string produced by
    ``_format_pipeline_injection()``, or ``""``.
    """
    stripped = prompt.strip()
    if not stripped or stripped.startswith("/"):
        return ""

    pending_path = detect_task_transition(root, prompt)
    if pending_path is None:
        if _has_pending_queue(root):
            pending_path = _pop_next_pending(root)
    if pending_path is None:
        return ""
    return _format_pipeline_injection(pending_path)


# ===================================================================
# Transition detection
# ===================================================================


def detect_task_transition(root: Path, prompt: str) -> Path | None:
    """Detect whether *prompt* starts a new task and, if so, capture the previous one.

    Returns the path to the newly-written pending JSON file, or ``None`` when
    no transition is detected.
    """
    stripped = prompt.strip()
    if not stripped or stripped.startswith("/"):
        return None

    lowered = stripped.lower()
    if any(term in lowered for term in _CANCELLATION_TERMS):
        return None

    old_task = get_last_completed_task(root)
    if old_task is None:
        return None

    old_name = old_task.get("task_name", "")
    new_name = _prompt_to_task_name(prompt)
    if not new_name:
        return None

    if _tasks_are_same(new_name, old_name):
        return None

    return _capture_pending_task(root, old_task)


# ===================================================================
# Task name helpers
# ===================================================================


def _prompt_to_task_name(prompt: str) -> str:
    """Return the first 3-4 words of *prompt* as a lowercase slug.

    Words with <= 2 characters are filtered out.
    """
    words: list[str] = []
    for raw in prompt.strip().split():
        cleaned = "".join(ch for ch in raw if ch.isalnum()).strip()
        if len(cleaned) > 2:
            words.append(cleaned)
        if len(words) >= 4:
            break
    if not words:
        return ""
    return _slugify(" ".join(words))


def _tasks_are_same(new_name: str, old_name: str) -> bool:
    """Return ``True`` when >= 40% of significant terms overlap."""
    new_terms = {
        t.lower() for t in re.split(r"[^a-zA-Z0-9]+", new_name) if len(t) > 2
    }
    old_terms = {
        t.lower() for t in re.split(r"[^a-zA-Z0-9]+", old_name) if len(t) > 2
    }

    if not new_terms or not old_terms:
        return False

    intersection = new_terms & old_terms
    smaller = min(len(new_terms), len(old_terms))
    if smaller == 0:
        return False
    return len(intersection) / smaller >= 0.4


# ===================================================================
# Last completed task
# ===================================================================


def get_last_completed_task(root: Path) -> dict[str, Any] | None:
    """Read the most recently completed task from the session registry, handoff, and
    git, and return a unified dictionary.

    Returns ``None`` when there is no task or no file changes were detected.
    """
    db_session = _query_last_session(root)
    task_name = ""
    transcript = ""

    if db_session:
        task_name = db_session.get("current_task_title") or db_session.get("name") or ""
        transcript = db_session.get("transcript_path") or ""

    if not transcript:
        transcript = _transcript_from_handoff(root) or ""

    files_changed = _recently_changed_files(root)
    if not files_changed:
        return None

    if not task_name:
        return None

    commit_range = _commit_range(root)
    test_results = _capture_test_results(root)

    return {
        "task_name": task_name,
        "transcript_path": transcript,
        "files_changed": files_changed,
        "commit_range": commit_range,
        "test_results": test_results,
        "captured_at": now_iso(),
    }


# ===================================================================
# SQLite helper
# ===================================================================


def _query_last_session(root: Path) -> dict[str, Any] | None:
    """Query ``.fcc/sessions.sqlite`` for the most recent session that has a
    *current_task_title* and one of the recognised statuses."""
    db_path = root / ".fcc" / "sessions.sqlite"
    if not db_path.is_file():
        return None

    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT session_id, current_task_title, name, status,
                   transcript_path, last_active_at
            FROM sessions
            WHERE current_task_title IS NOT NULL
              AND status IN ('resumable', 'failed', 'active')
            ORDER BY last_active_at DESC
            LIMIT 1
            """
        ).fetchone()
        conn.close()
    except (sqlite3.DatabaseError, sqlite3.OperationalError, OSError):
        return None

    if row is None:
        return None

    return {
        "session_id": row["session_id"],
        "current_task_title": row["current_task_title"],
        "name": row["name"],
        "status": row["status"],
        "transcript_path": row["transcript_path"],
        "last_active_at": row["last_active_at"],
    }


# ===================================================================
# Handoff helper
# ===================================================================


def _transcript_from_handoff(root: Path) -> str | None:
    """Scan ``.fcc/context/handoff.md`` for a ``.jsonl`` transcript path."""
    handoff_path = root / ".fcc" / "context" / "handoff.md"
    if not handoff_path.is_file():
        return None

    try:
        text = handoff_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    match = re.search(r"(\S+\.jsonl)", text)
    if match:
        return match.group(1)
    return None


# ===================================================================
# Git helpers
# ===================================================================


def _recently_changed_files(root: Path) -> list[str]:
    """Return file names changed since the last commit, falling back to the
    initial commit when there is only one commit."""
    try:
        completed = subprocess.run(
            ["git", "diff", "--name-only", "HEAD~1"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(root),
        )
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        return []

    if completed.returncode == 0 and completed.stdout.strip():
        return [
            f for f in completed.stdout.strip().splitlines() if f.strip()
        ]

    # Fallback: git diff --name-only HEAD
    try:
        fallback = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(root),
        )
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        return []

    if fallback.returncode == 0 and fallback.stdout.strip():
        return [
            f for f in fallback.stdout.strip().splitlines() if f.strip()
        ]

    return []


def _commit_range(root: Path) -> str:
    """Return the last two commit hashes separated by ``..``, e.g.
    ``abc123..def456``.  Returns an empty string when git is unavailable."""
    try:
        completed = subprocess.run(
            ["git", "log", "-n", "2", "--format=%H"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(root),
        )
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        return ""

    if completed.returncode != 0:
        return ""

    hashes = [h.strip() for h in completed.stdout.strip().splitlines() if h.strip()]
    if len(hashes) >= 2:
        return f"{hashes[1]}..{hashes[0]}"
    if len(hashes) == 1:
        return hashes[0]
    return ""


# ===================================================================
# Test runner
# ===================================================================


def _capture_test_results(root: Path) -> dict[str, Any] | None:
    """Run ``uv run pytest --tb=no -q --no-header`` and parse the summary.

    Returns a dict with ``passed``, ``failed``, ``total``, and
    ``failures`` keys, or ``None`` when pytest is unavailable.
    """
    try:
        completed = subprocess.run(
            ["uv", "run", "pytest", "--tb=no", "-q", "--no-header"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(root),
        )
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        return None

    output = completed.stdout.strip()
    if not output:
        return None

    # Parse the pytest summary line, e.g.:
    # "5 passed, 1 failed in 0.42s"
    # "... 3 passed ..."
    passed = 0
    failed = 0
    total = 0

    passed_match = re.search(r"(\d+)\s+passed", output)
    if passed_match:
        passed = int(passed_match.group(1))

    failed_match = re.search(r"(\d+)\s+failed", output)
    if failed_match:
        failed = int(failed_match.group(1))

    total = passed + failed

    # Capture failure names from the output lines
    # pytest -q prints "FAILED tests/test_file.py::test_name" lines
    failure_names: list[str] = []
    for line in output.splitlines():
        if line.strip().startswith("FAILED "):
            failure_names.append(line.strip())

    return {
        "passed": passed,
        "failed": failed,
        "total": total,
        "failures": failure_names,
    }


# ===================================================================
# Pending-task capture
# ===================================================================


def _capture_pending_task(root: Path, task: dict[str, Any]) -> Path:
    """Write a pending-task JSON file into ``.fcc/debugger/pending/`` and
    return its path."""
    pending = root / PENDING_DIR
    pending.mkdir(parents=True, exist_ok=True)

    task_name = task.get("task_name", "unknown")
    slug = _slugify(task_name) or "task"
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    filename = f"{timestamp}-{slug}.json"
    filepath = pending / filename

    filepath.write_text(json.dumps(task, indent=2, ensure_ascii=False), encoding="utf-8")
    return filepath


# ===================================================================
# Pending queue
# ===================================================================


def _has_pending_queue(root: Path) -> bool:
    """Return ``True`` when ``.fcc/debugger/pending/`` contains at least one
    ``.json`` file."""
    pending = root / PENDING_DIR
    if not pending.is_dir():
        return False
    return any(pending.glob("*.json"))


def _pop_next_pending(root: Path) -> Path | None:
    """Return the oldest pending ``.json`` file path, or ``None`` when the
    queue is empty or all entries are stale.

    Stale entries (> ``QUEUE_STALE_HOURS``) are moved to ``failed/``.
    """
    pending = root / PENDING_DIR
    if not pending.is_dir():
        return None

    json_files = sorted(
        pending.glob("*.json"), key=lambda p: p.stat().st_mtime
    )
    if not json_files:
        return None

    stale_threshold = datetime.now(UTC) - timedelta(hours=QUEUE_STALE_HOURS)

    for filepath in json_files:
        mtime = datetime.fromtimestamp(filepath.stat().st_mtime, UTC)
        if mtime < stale_threshold:
            failed_dir = root / FAILED_DIR
            failed_dir.mkdir(parents=True, exist_ok=True)
            try:
                filepath.rename(failed_dir / filepath.name)
            except OSError:
                pass
            continue
        return filepath

    return None


def _flush_all_pending_to_skipped(root: Path) -> None:
    """Move every pending ``.json`` file into ``skipped/``."""
    pending = root / PENDING_DIR
    if not pending.is_dir():
        return

    skipped = root / SKIPPED_DIR
    skipped.mkdir(parents=True, exist_ok=True)

    for json_file in pending.glob("*.json"):
        try:
            json_file.rename(skipped / json_file.name)
        except OSError:
            pass


# ===================================================================
# Lockfile
# ===================================================================


def _lockfile_exists(root: Path) -> bool:
    """Check ``.fcc/debugger/lock`` and return ``True`` when a *live* lock
    exists.

    Cleans up stale/dead locks: reads the PID from the lockfile and verifies
    it is alive.  Also checks the lock timestamp against
    ``LOCK_TIMEOUT_SECONDS``.
    """
    lock_path = root / LOCKFILE
    if not lock_path.is_file():
        return False

    try:
        raw = lock_path.read_text(encoding="utf-8").strip()
        pid = int(raw)
    except (ValueError, OSError):
        # Corrupted lock -- clean it up
        _release_lock(root)
        return False

    # Check PID alive
    if not _pid_is_alive(pid):
        _release_lock(root)
        return False

    # Check timeout
    try:
        mtime = datetime.fromtimestamp(lock_path.stat().st_mtime, UTC)
    except OSError:
        _release_lock(root)
        return False

    if (datetime.now(UTC) - mtime).total_seconds() > LOCK_TIMEOUT_SECONDS:
        _release_lock(root)
        return False

    return True


def _pid_is_alive(pid: int) -> bool:
    """Return ``True`` when the process identified by *pid* is running."""
    if pid <= 0:
        return False

    if os.name == "nt":
        try:
            completed = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (FileNotFoundError, subprocess.SubprocessError, OSError):
            return False
        return str(pid) in completed.stdout

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # process exists but we lack permission
    return True


def _release_lock(root: Path) -> None:
    """Delete the lockfile if it exists."""
    lock_path = root / LOCKFILE
    if lock_path.exists():
        try:
            lock_path.unlink()
        except OSError:
            pass


# ===================================================================
# Slug helper
# ===================================================================


def _slugify(text: str) -> str:
    """Convert *text* into a filesystem-safe slug, max 64 characters."""
    words: list[str] = []
    for raw in text.lower().replace("_", "-").split():
        cleaned = "".join(ch for ch in raw if ch.isalnum() or ch == "-").strip("-")
        if cleaned:
            words.append(cleaned)
        if len(words) >= 8:
            break

    if not words:
        return "task"

    slug = "-".join(words)
    return slug[:64]


# ===================================================================
# Pipeline injection formatting
# ===================================================================


def _format_pipeline_injection(pending_path: Path) -> str:
    """Build the context-injection string that instructs the agent to run the
    debugger-then-fixer pipeline."""
    try:
        data = json.loads(pending_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return ""

    task_name = data.get("task_name", "unknown")
    files = data.get("files_changed", [])
    test_results = data.get("test_results")
    commit_range = data.get("commit_range", "")

    # File list (capped at 5 + "and N more")
    file_list = files[:5]
    if len(files) > 5:
        file_list.append("...and {} more".format(len(files) - 5))
    files_str = "\n".join(f"  - {f}" for f in file_list) if file_list else "  (none)"

    # Test results
    test_lines: list[str] = []
    if test_results and isinstance(test_results, dict):
        p = test_results.get("passed", 0)
        f = test_results.get("failed", 0)
        t = test_results.get("total", 0)
        test_lines.append(
            f"- Test Results: {p} passed, {f} failed ({t} total)"
        )
        failures = test_results.get("failures", [])
        if failures:
            for fail in failures[:5]:
                test_lines.append(f"  {fail}")
            if len(failures) > 5:
                test_lines.append(f"  ...and {len(failures) - 5} more failures")

    tests_str = "\n".join(test_lines) if test_lines else "- Test Results: N/A"

    # Commit range
    commit_str = commit_range if commit_range else "N/A"

    injection = (
        f"FCC Agent Debugger: The task '{task_name}' was just completed.\n"
        f"\n"
        f"Commit range: {commit_str}\n"
        f"Files changed:\n{files_str}\n"
        f"\n"
        f"{tests_str}\n"
        f"\n"
        "To validate this work, dispatch the fcc-agent-debugger subagent to analyze "
        "the completed task. If issues are found, chain the fcc-agent-fixer subagent "
        "to apply fixes in a worktree. Use run_in_background: true for each "
        "dispatch and isolate all fix work in a git worktree under "
        ".claude/worktrees/."
    )

    return injection
