"""Tests for debugger trigger module (transition detection, queue, lockfile)."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from unittest import mock

import pytest

from core.debugger.trigger import (
    PENDING_DIR,
    LOCKFILE,
    _capture_pending_task,
    _capture_test_results,
    _commit_range,
    _flush_all_pending_to_skipped,
    _format_pipeline_injection,
    _has_pending_queue,
    _lockfile_exists,
    _pid_is_alive,
    _pop_next_pending,
    _prompt_to_task_name,
    _query_last_session,
    _recently_changed_files,
    _release_lock,
    _slugify,
    _tasks_are_same,
    _transcript_from_handoff,
    debugger_pipeline_context,
    detect_task_transition,
    get_last_completed_task,
)


# ===================================================================
# _prompt_to_task_name
# ===================================================================


def test_prompt_to_task_name_normal() -> None:
    result = _prompt_to_task_name("Implement the new user authentication flow")
    assert result == "implement-the-new-user"


def test_prompt_to_task_name_short() -> None:
    result = _prompt_to_task_name("Fix bug")
    assert result == "fix-bug"


def test_prompt_to_task_name_single_word() -> None:
    result = _prompt_to_task_name("Refactor")
    assert result == "refactor"


def test_prompt_to_task_name_filters_short_words() -> None:
    result = _prompt_to_task_name("do a new feature")
    assert result == "new-feature"


# ===================================================================
# _tasks_are_same
# ===================================================================


def test_tasks_are_same_exact() -> None:
    assert _tasks_are_same("fix-login-bug", "fix-login-bug") is True


def test_tasks_are_same_continuation() -> None:
    # 3 shared terms ("add", "user", "login") out of 4 total new = 75% >= 40%
    assert (
        _tasks_are_same(
            "add-user-login-form",
            "add-user-login-api",
        )
        is True
    )


def test_tasks_are_same_different() -> None:
    assert (
        _tasks_are_same("fix-login-bug", "refactor-database-schema") is False
    )


def test_tasks_are_same_no_overlap() -> None:
    assert _tasks_are_same("add-tests", "deploy-server") is False


def test_tasks_are_same_edge_case_empty() -> None:
    assert _tasks_are_same("", "something") is False
    assert _tasks_are_same("something", "") is False
    assert _tasks_are_same("", "") is False


def test_tasks_are_same_edge_case_single_word_different() -> None:
    assert _tasks_are_same("fix", "deploy") is False


# ===================================================================
# detect_task_transition
# ===================================================================


def test_detect_transition_skips_slash_command(tmp_path: Path) -> None:
    result = detect_task_transition(tmp_path, "/code-review")
    assert result is None


def test_detect_transition_skips_empty_prompt(tmp_path: Path) -> None:
    result = detect_task_transition(tmp_path, "   ")
    assert result is None


def test_detect_transition_skips_cancellation(tmp_path: Path) -> None:
    result = detect_task_transition(tmp_path, "cancel the previous task")
    assert result is None


def test_detect_transition_no_db_returns_none(tmp_path: Path) -> None:
    result = detect_task_transition(tmp_path, "Build a new feature X")
    assert result is None


# ===================================================================
# _capture_pending_task
# ===================================================================


def test_capture_pending_task_writes_file(tmp_path: Path) -> None:
    task = {"task_name": "fix-bug-42", "files_changed": ["app.py"]}
    path = _capture_pending_task(tmp_path, task)
    assert path.is_file()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["task_name"] == "fix-bug-42"
    assert data["files_changed"] == ["app.py"]


# ===================================================================
# _query_last_session
# ===================================================================


def test_query_last_session_empty(tmp_path: Path) -> None:
    root = tmp_path / "empty"
    root.mkdir()
    result = _query_last_session(root)
    assert result is None


def test_query_last_session_with_data(tmp_path: Path) -> None:
    root = tmp_path
    db_dir = root / ".fcc"
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / "sessions.sqlite"

    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE sessions (
            session_id TEXT,
            current_task_title TEXT,
            name TEXT,
            status TEXT,
            transcript_path TEXT,
            last_active_at TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?)",
        ("s1", "fix-login-bug", "Fix Login Bug", "resumable", "/tmp/t.jsonl", "2025-01-01T00:00:00Z"),
    )
    conn.commit()
    conn.close()

    result = _query_last_session(root)
    assert result is not None
    assert result["current_task_title"] == "fix-login-bug"
    assert result["status"] == "resumable"


# ===================================================================
# _transcript_from_handoff
# ===================================================================


def test_transcript_from_handoff_finds_jsonl(tmp_path: Path) -> None:
    ctx_dir = tmp_path / ".fcc" / "context"
    ctx_dir.mkdir(parents=True)
    (ctx_dir / "handoff.md").write_text(
        "Transcript: /home/user/.claude/projects/sess123.jsonl\nOther text.",
        encoding="utf-8",
    )
    result = _transcript_from_handoff(tmp_path)
    assert result == "/home/user/.claude/projects/sess123.jsonl"


def test_transcript_from_handoff_no_file(tmp_path: Path) -> None:
    result = _transcript_from_handoff(tmp_path)
    assert result is None


# ===================================================================
# _recently_changed_files
# ===================================================================


def test_recently_changed_files_no_git(tmp_path: Path) -> None:
    result = _recently_changed_files(tmp_path)
    assert isinstance(result, list)
    assert result == []


# ===================================================================
# _has_pending_queue
# ===================================================================


def test_has_pending_queue_empty(tmp_path: Path) -> None:
    assert _has_pending_queue(tmp_path) is False


def test_has_pending_queue_with_items(tmp_path: Path) -> None:
    pending = tmp_path / PENDING_DIR
    pending.mkdir(parents=True)
    (pending / "20250101T000000-test.json").write_text("{}", encoding="utf-8")
    assert _has_pending_queue(tmp_path) is True


# ===================================================================
# _pop_next_pending
# ===================================================================


def test_pop_next_pending_empty(tmp_path: Path) -> None:
    assert _pop_next_pending(tmp_path) is None


def test_pop_next_pending_returns_oldest(tmp_path: Path) -> None:
    pending = tmp_path / PENDING_DIR
    pending.mkdir(parents=True)
    first = pending / "20250101T000000-first.json"
    second = pending / "20250101T010000-second.json"
    first.write_text("{}", encoding="utf-8")
    # Ensure second has a later mtime
    time.sleep(0.02)
    second.write_text("{}", encoding="utf-8")
    result = _pop_next_pending(tmp_path)
    assert result is not None
    assert result.name == "20250101T000000-first.json"


# ===================================================================
# _flush_all_pending_to_skipped
# ===================================================================


def test_flush_to_skipped(tmp_path: Path) -> None:
    from core.debugger.trigger import SKIPPED_DIR

    pending = tmp_path / PENDING_DIR
    pending.mkdir(parents=True)
    (pending / "task1.json").write_text("{}", encoding="utf-8")
    (pending / "task2.json").write_text("{}", encoding="utf-8")

    _flush_all_pending_to_skipped(tmp_path)

    skipped = tmp_path / SKIPPED_DIR
    assert (skipped / "task1.json").is_file()
    assert (skipped / "task2.json").is_file()
    assert not (pending / "task1.json").exists()
    assert not (pending / "task2.json").exists()


# ===================================================================
# Lockfile tests
# ===================================================================


def test_lockfile_does_not_exist(tmp_path: Path) -> None:
    assert _lockfile_exists(tmp_path) is False


def test_lockfile_with_dead_pid(tmp_path: Path) -> None:
    lock_path = tmp_path / LOCKFILE
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    # Use a very high PID that almost certainly doesn't exist
    lock_path.write_text("9999999", encoding="utf-8")
    result = _lockfile_exists(tmp_path)
    # Should clean up the dead lock
    assert result is False


def test_release_lock(tmp_path: Path) -> None:
    lock_path = tmp_path / LOCKFILE
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text("1234", encoding="utf-8")
    _release_lock(tmp_path)
    assert lock_path.exists() is False


# ===================================================================
# _slugify
# ===================================================================


def test_slugify_normal() -> None:
    assert _slugify("Fix Login Bug") == "fix-login-bug"


def test_slugify_with_special_chars() -> None:
    assert _slugify("Hello! World? #test") == "hello-world-test"


def test_slugify_empty() -> None:
    assert _slugify("") == "task"


def test_slugify_max_length() -> None:
    long_name = "a" * 100
    result = _slugify(long_name)
    assert len(result) <= 64


# ===================================================================
# _format_pipeline_injection
# ===================================================================


def test_format_injection_includes_task_name(tmp_path: Path) -> None:
    pending = tmp_path / "pending.json"
    pending.write_text(
        json.dumps({
            "task_name": "fix-login-bug",
            "files_changed": ["login.py"],
            "commit_range": "abc..def",
        }),
        encoding="utf-8",
    )
    result = _format_pipeline_injection(pending)
    assert "fix-login-bug" in result
    assert "login.py" in result


def test_format_injection_with_test_failures(tmp_path: Path) -> None:
    pending = tmp_path / "pending.json"
    pending.write_text(
        json.dumps({
            "task_name": "refactor-db",
            "files_changed": ["db.py"],
            "test_results": {
                "passed": 3,
                "failed": 1,
                "total": 4,
                "failures": ["FAILED tests/test_db.py::test_query"],
            },
        }),
        encoding="utf-8",
    )
    result = _format_pipeline_injection(pending)
    assert "3 passed, 1 failed" in result
    assert "test_query" in result


def test_format_injection_truncates_long_file_list(tmp_path: Path) -> None:
    files = [f"file_{i}.py" for i in range(10)]
    pending = tmp_path / "pending.json"
    pending.write_text(
        json.dumps({
            "task_name": "big-refactor",
            "files_changed": files,
        }),
        encoding="utf-8",
    )
    result = _format_pipeline_injection(pending)
    assert "file_0.py" in result
    assert "file_4.py" in result
    assert "and 5 more" in result
    assert "file_9.py" not in result


def test_format_injection_missing_file(tmp_path: Path) -> None:
    result = _format_pipeline_injection(tmp_path / "nonexistent.json")
    assert result == ""


# ===================================================================
# _pid_is_alive
# ===================================================================


def test_pid_is_alive_zero() -> None:
    assert _pid_is_alive(0) is False


def test_pid_is_alive_negative() -> None:
    assert _pid_is_alive(-1) is False


# ===================================================================
# debugger_pipeline_context
# ===================================================================


def test_pipeline_context_empty_prompt(tmp_path: Path) -> None:
    result = debugger_pipeline_context("   ", tmp_path)
    assert result == ""


def test_pipeline_context_no_previous_task(tmp_path: Path) -> None:
    result = debugger_pipeline_context("Do something new", tmp_path)
    assert result == ""


def test_pipeline_context_with_pending_queue(tmp_path: Path) -> None:
    pending = tmp_path / PENDING_DIR
    pending.mkdir(parents=True)
    task = {
        "task_name": "fix-thing",
        "files_changed": ["thing.py"],
        "commit_range": "abc..def",
        "test_results": {"passed": 5, "failed": 0, "total": 5, "failures": []},
    }
    (pending / "20250101T000000-fix-thing.json").write_text(
        json.dumps(task), encoding="utf-8"
    )

    result = debugger_pipeline_context("Do something new", tmp_path)
    assert "fix-thing" in result
    assert "thing.py" in result


# ===================================================================
# _capture_test_results
# ===================================================================


def test_capture_test_results_no_pytest(tmp_path: Path) -> None:
    result = _capture_test_results(tmp_path)
    # May be None if uv/pytest not available, or may return results
    # if they happen to be installed. Either is fine.
    assert result is None or isinstance(result, dict)


# ===================================================================
# _commit_range
# ===================================================================


def test_commit_range_no_git(tmp_path: Path) -> None:
    result = _commit_range(tmp_path)
    assert result == ""


# ===================================================================
# get_last_completed_task
# ===================================================================


def test_get_last_completed_task_no_db(tmp_path: Path) -> None:
    result = get_last_completed_task(tmp_path)
    assert result is None
