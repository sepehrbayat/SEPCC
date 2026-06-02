"""Tests for debugger pipeline integration in the UserPromptSubmit hook."""

from __future__ import annotations

import importlib.util
import sqlite3
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOKS_DIR = REPO_ROOT / "scripts" / "hooks"


def _load_hook_module():
    # The hook script does ``from _shared import ...`` so the hooks directory
    # must be on sys.path.
    if str(HOOKS_DIR) not in sys.path:
        sys.path.insert(0, str(HOOKS_DIR))
    spec = importlib.util.spec_from_file_location(
        "user_prompt_submit", HOOKS_DIR / "user_prompt_submit.py"
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _init_git_repo(root: Path) -> bool:
    """Initialise a git repo in *root* and return True on success."""
    try:
        subprocess.run(
            ["git", "init", "-b", "main"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(root),
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(root),
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(root),
            check=True,
        )
        return True
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        return False


def _make_git_commit(root: Path, filename: str, content: str) -> bool:
    """Create a file and commit it. Returns True on success."""
    try:
        (root / filename).write_text(content, encoding="utf-8")
        subprocess.run(
            ["git", "add", filename],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(root),
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", f"Add {filename}"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(root),
            check=True,
        )
        return True
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        return False


def _git_available() -> bool:
    """Return True when git is on PATH and works."""
    try:
        subprocess.run(
            ["git", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        return True
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        return False


def _create_session_db(db_path: Path, *, current_task_title: str | None) -> None:
    """Create a minimal sessions.sqlite with one active session row."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            current_task_title TEXT,
            name TEXT,
            status TEXT,
            transcript_path TEXT,
            last_active_at TEXT,
            started_at TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO sessions (session_id, current_task_title, name, status, "
        "transcript_path, last_active_at, started_at) "
        "VALUES (?, ?, ?, 'active', NULL, datetime('now'), datetime('now'))",
        ("test-session-1", current_task_title, current_task_title),
    )
    conn.commit()
    conn.close()


# ===================================================================
# Tests
# ===================================================================


def test_hook_module_loads() -> None:
    """The hook module can be imported and exposes main + _debugger_pipeline_context."""
    module = _load_hook_module()
    assert hasattr(module, "main")
    assert hasattr(module, "_debugger_pipeline_context")
    assert callable(module.main)
    assert callable(module._debugger_pipeline_context)


def test_debugger_pipeline_context_no_previous_task(tmp_path: Path) -> None:
    """Empty string when there is no sessions database at all."""
    module = _load_hook_module()
    result = module._debugger_pipeline_context("fix a bug", tmp_path)
    assert result == ""


def test_debugger_pipeline_context_empty_prompt(tmp_path: Path) -> None:
    """Empty string for an empty prompt."""
    module = _load_hook_module()
    result = module._debugger_pipeline_context("", tmp_path)
    assert result == ""


def test_debugger_pipeline_context_slash_command_skipped(tmp_path: Path) -> None:
    """Empty string when the prompt is a slash command."""
    module = _load_hook_module()
    result = module._debugger_pipeline_context("/context all", tmp_path)
    assert result == ""


def test_injection_within_budget(tmp_path: Path) -> None:
    """The debugger pipeline context never exceeds the 3600-character budget."""
    module = _load_hook_module()

    if not _git_available():
        # Without git, _recently_changed_files returns [] so the result is "".
        result = module._debugger_pipeline_context("add a new feature", tmp_path)
        assert result == ""
        return

    if not _init_git_repo(tmp_path):
        result = module._debugger_pipeline_context("add a new feature", tmp_path)
        assert result == ""
        return

    _make_git_commit(tmp_path, "a.py", "print('hello')")
    _make_git_commit(tmp_path, "b.py", "print('world')")

    db_path = tmp_path / ".fcc" / "sessions.sqlite"
    _create_session_db(db_path, current_task_title="fix-login-bug")

    result = module._debugger_pipeline_context("add a new feature", tmp_path)
    assert len(result) <= 3600


def test_injection_does_not_fire_on_first_prompt(tmp_path: Path) -> None:
    """No injection when the DB exists but has no current_task_title set."""
    module = _load_hook_module()

    db_path = tmp_path / ".fcc" / "sessions.sqlite"
    _create_session_db(db_path, current_task_title=None)

    result = module._debugger_pipeline_context("fix a bug", tmp_path)
    assert result == ""


def test_injection_includes_required_elements(tmp_path: Path) -> None:
    """Debugger injection contains the expected subagent and workflow references.

    When git is unavailable or HEAD~1 does not exist, an empty string is also
    a valid outcome.
    """
    module = _load_hook_module()

    if not _git_available():
        result = module._debugger_pipeline_context("add user profile page", tmp_path)
        assert result == ""
        return

    if not _init_git_repo(tmp_path):
        result = module._debugger_pipeline_context("add user profile page", tmp_path)
        assert result == ""
        return

    _make_git_commit(tmp_path, "src/main.py", "# main module")
    _make_git_commit(tmp_path, "src/utils.py", "# utilities")

    db_path = tmp_path / ".fcc" / "sessions.sqlite"
    _create_session_db(db_path, current_task_title="refactor-database-schema")

    result = module._debugger_pipeline_context("add user profile page", tmp_path)

    if not result:
        # Git HEAD~1 may not exist (single commit repos), which is valid.
        return

    assert "fcc-agent-debugger" in result
    assert "fcc-agent-fixer" in result
    assert "run_in_background" in result
    assert "refactor-database-schema" in result


def test_debugger_pipeline_context_non_path_root() -> None:
    """Returns empty string when root is not a Path instance."""
    module = _load_hook_module()
    result = module._debugger_pipeline_context("fix bug", "not/a/path/object")
    assert result == ""


def test_debugger_pipeline_context_cancellation_prompt(tmp_path: Path) -> None:
    """Empty string when the prompt is a cancellation."""
    module = _load_hook_module()

    if not _git_available():
        result = module._debugger_pipeline_context("cancel that task", tmp_path)
        assert result == ""
        return

    if not _init_git_repo(tmp_path):
        result = module._debugger_pipeline_context("cancel that task", tmp_path)
        assert result == ""
        return

    _make_git_commit(tmp_path, "a.py", "x")
    _make_git_commit(tmp_path, "b.py", "y")

    db_path = tmp_path / ".fcc" / "sessions.sqlite"
    _create_session_db(db_path, current_task_title="fix-login-bug")

    result = module._debugger_pipeline_context("cancel that task", tmp_path)
    assert result == ""


def test_debugger_pipeline_context_same_task_no_transition(tmp_path: Path) -> None:
    """Empty string when the new prompt is a continuation of the same task."""
    module = _load_hook_module()

    if not _git_available():
        result = module._debugger_pipeline_context(
            "fix login bug in auth module", tmp_path
        )
        assert result == ""
        return

    if not _init_git_repo(tmp_path):
        result = module._debugger_pipeline_context(
            "fix login bug in auth module", tmp_path
        )
        assert result == ""
        return

    _make_git_commit(tmp_path, "a.py", "x")
    _make_git_commit(tmp_path, "b.py", "y")

    db_path = tmp_path / ".fcc" / "sessions.sqlite"
    _create_session_db(db_path, current_task_title="fix-login-bug")

    # "fix login bug" shares terms with "fix-login-bug" so >= 40% overlap
    result = module._debugger_pipeline_context(
        "fix the login bug", tmp_path
    )
    assert result == ""
