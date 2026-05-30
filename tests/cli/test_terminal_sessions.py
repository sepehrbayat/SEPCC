import json
import os
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from cli.session_registry import (
    SESSION_COLUMNS,
    SessionRegistry,
    discover_latest_transcript,
    parse_transcript,
)
from cli.session_resume import (
    build_continuity_prompt,
    choose_resume_session,
    format_sessions_table,
)
from config.settings import Settings


def _settings() -> Settings:
    return Settings.model_construct(
        host="0.0.0.0",
        port=9191,
        anthropic_auth_token="proxy-token",
        model="deepseek/deepseek-v4-pro",
        fcc_auto_resume_last_session=True,
        fcc_auto_resume_max_age_days=7,
        fcc_auto_resume_project_scoped=True,
        fcc_session_picker_on_ambiguous=True,
    )


def _write_transcript(
    project_root: Path,
    native_id: str,
    *,
    user: str = "Fix auth middleware",
    assistant: str = "Updated the auth middleware and tests",
) -> Path:
    transcript = project_root / ".claude-transcripts" / f"{native_id}.jsonl"
    transcript.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "sessionId": native_id,
            "cwd": str(project_root),
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": user}],
            },
        },
        {
            "sessionId": native_id,
            "cwd": str(project_root),
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": assistant}],
            },
        },
    ]
    transcript.write_text(
        "\n".join(json.dumps(row) for row in rows),
        encoding="utf-8",
    )
    os.utime(transcript, None)
    return transcript


def _create_resumable_session(
    registry: SessionRegistry,
    project_root: Path,
    *,
    native_id: str = "native-123",
    name: str = "fix-auth-middleware",
) -> tuple[str, Path]:
    transcript = _write_transcript(project_root, native_id)
    record = registry.create_terminal_session(
        cwd=project_root,
        command=["claude"],
        provider="deepseek",
        model="deepseek/deepseek-v4-pro",
        name=name,
    )
    registry.update(
        record.session_id,
        status="resumable",
        native_session_id=native_id,
        transcript_path=str(transcript),
        last_active_at=datetime.now(UTC).isoformat(),
    )
    return record.session_id, transcript


def test_starting_and_finishing_session_records_resumable_row(tmp_path: Path) -> None:
    registry = SessionRegistry(tmp_path)
    transcript = _write_transcript(tmp_path, "native-abc")
    record = registry.create_terminal_session(
        cwd=tmp_path,
        command=["claude"],
        provider="deepseek",
        model="deepseek/deepseek-v4-pro",
    )

    registry.finish_terminal_session(
        record.session_id,
        return_code=0,
        transcript=parse_transcript(transcript),
    )

    updated = registry.get(record.session_id)
    assert updated is not None
    assert updated.status == "resumable"
    assert updated.native_session_id == "native-abc"
    assert updated.transcript_path == str(transcript)
    assert updated.last_prompt_excerpt == "Fix auth middleware"
    assert updated.name == "fix-auth-middleware"


def test_stale_active_session_becomes_resumable(tmp_path: Path) -> None:
    registry = SessionRegistry(tmp_path)
    record = registry.create_terminal_session(
        cwd=tmp_path,
        command=["claude"],
        provider="deepseek",
        model="deepseek/deepseek-v4-pro",
    )
    stale = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    registry.update(record.session_id, pid=999999, last_heartbeat_at=stale)

    with patch("cli.session_registry.process_is_running", return_value=False):
        healed = registry.heal_stale_active_sessions()

    updated = registry.get(record.session_id)
    assert healed == 1
    assert updated is not None
    assert updated.status == "resumable"
    assert updated.pid is None


def test_live_active_session_is_not_auto_resume_candidate(tmp_path: Path) -> None:
    registry = SessionRegistry(tmp_path)
    record = registry.create_terminal_session(
        cwd=tmp_path,
        command=["claude"],
        provider="deepseek",
        model="deepseek/deepseek-v4-pro",
    )
    stale = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    registry.update(record.session_id, pid=1234, last_heartbeat_at=stale)

    with patch("cli.session_registry.process_is_running", return_value=True):
        healed = registry.heal_stale_active_sessions()

    assert healed == 0
    assert registry.resumable_for_project() == []
    active = registry.get(record.session_id)
    assert active is not None
    assert active.status == "active"


def test_fcc_launch_auto_resumes_latest_native_session(tmp_path: Path) -> None:
    from cli.entrypoints import launch_claude

    registry = SessionRegistry(tmp_path)
    _, transcript = _create_resumable_session(
        registry, tmp_path, native_id="native-latest"
    )

    with (
        patch("cli.entrypoints.get_settings", return_value=_settings()),
        patch("cli.entrypoints._preflight_proxy", return_value=None),
        patch("cli.entrypoints.shutil.which", return_value="claude"),
        patch("cli.entrypoints.maybe_update_claude_code"),
        patch(
            "cli.entrypoints.discover_latest_transcript",
            return_value=parse_transcript(transcript),
        ),
        patch("cli.entrypoints.subprocess.Popen") as popen,
        pytest.raises(SystemExit) as exc_info,
    ):
        process = popen.return_value
        process.pid = 1001
        process.wait.return_value = 0
        launch_claude([str(tmp_path)], auto_resume=True)

    command = popen.call_args.args[0]
    assert exc_info.value.code == 0
    assert command[:4] == [
        "claude",
        "--dangerously-skip-permissions",
        "--resume",
        "native-latest",
    ]
    assert "--append-system-prompt" not in command
    assert popen.call_args.kwargs["cwd"] == str(tmp_path)


def test_fcc_launch_resumes_explicit_session_id(tmp_path: Path) -> None:
    from cli.entrypoints import launch_claude

    registry = SessionRegistry(tmp_path)
    first_id, first_transcript = _create_resumable_session(
        registry,
        tmp_path,
        native_id="native-first",
        name="first-task",
    )
    _create_resumable_session(
        registry,
        tmp_path,
        native_id="native-second",
        name="second-task",
    )

    with (
        patch("cli.entrypoints.get_settings", return_value=_settings()),
        patch("cli.entrypoints._preflight_proxy", return_value=None),
        patch("cli.entrypoints.shutil.which", return_value="claude"),
        patch("cli.entrypoints.maybe_update_claude_code"),
        patch(
            "cli.entrypoints.discover_latest_transcript",
            return_value=parse_transcript(first_transcript),
        ),
        patch("cli.entrypoints.subprocess.Popen") as popen,
        pytest.raises(SystemExit) as exc_info,
    ):
        process = popen.return_value
        process.pid = 1002
        process.wait.return_value = 0
        launch_claude([str(tmp_path)], resume_ref=first_id)

    assert exc_info.value.code == 0
    assert "--resume" in popen.call_args.args[0]
    assert "native-first" in popen.call_args.args[0]


def test_missing_native_transcript_falls_back_to_compact_handoff(
    tmp_path: Path,
) -> None:
    from cli.entrypoints import launch_claude

    context_dir = tmp_path / ".fcc" / "context"
    context_dir.mkdir(parents=True)
    (context_dir / "handoff.md").write_text(
        "\n".join(
            [
                "# FCC Handoff",
                "",
                "## Must Not Forget",
                "- Keep FCC as the router.",
                "",
                "## Current State",
                "- Session resume layer is being tested.",
                "",
                "## Decisions",
                "- Use native Claude resume when transcript exists.",
                "",
                "## Next Steps",
                "- Run the context session tests.",
            ]
        ),
        encoding="utf-8",
    )
    raw_transcript = tmp_path / "raw-old-transcript.jsonl"
    raw_transcript.write_text("RAW OLD TRANSCRIPT SHOULD NOT BE INJECTED", "utf-8")
    registry = SessionRegistry(tmp_path)
    record = registry.create_terminal_session(
        cwd=tmp_path,
        command=["claude"],
        provider="deepseek",
        model="deepseek/deepseek-v4-pro",
        name="resume-session-persistence",
        native_session_id="native-missing",
    )
    missing_path = tmp_path / "missing-transcript.jsonl"
    registry.update(
        record.session_id,
        status="resumable",
        transcript_path=str(missing_path),
        native_session_id="native-missing",
    )

    with (
        patch("cli.entrypoints.get_settings", return_value=_settings()),
        patch("cli.entrypoints._preflight_proxy", return_value=None),
        patch("cli.entrypoints.shutil.which", return_value="claude"),
        patch("cli.entrypoints.maybe_update_claude_code"),
        patch("cli.session_resume.discover_latest_transcript", return_value=None),
        patch("cli.entrypoints.discover_latest_transcript", return_value=None),
        patch("cli.entrypoints.subprocess.Popen") as popen,
        pytest.raises(SystemExit),
    ):
        process = popen.return_value
        process.pid = 1003
        process.wait.return_value = 0
        launch_claude([str(tmp_path)], resume_ref=record.session_id)

    command = popen.call_args.args[0]
    prompt = command[command.index("--append-system-prompt") + 1]
    old_record = registry.get(record.session_id)
    continuations = [
        item
        for item in registry.list_recent(limit=10)
        if item.parent_session_id == record.session_id
    ]
    assert old_record is not None
    assert old_record.status == "missing_transcript"
    assert len(continuations) == 1
    assert "--resume" not in command
    assert "FCC compact resume context" in prompt
    assert "Session resume layer is being tested" in prompt
    assert "RAW OLD TRANSCRIPT" not in prompt


def test_multiple_resumable_sessions_trigger_picker(tmp_path: Path) -> None:
    registry = SessionRegistry(tmp_path)
    latest_id, _ = _create_resumable_session(
        registry,
        tmp_path,
        native_id="latest",
        name="latest-task",
    )
    older_id, _ = _create_resumable_session(
        registry,
        tmp_path,
        native_id="older",
        name="older-task",
    )
    now = datetime.now(UTC)
    registry.update(latest_id, last_active_at=now.isoformat())
    registry.update(older_id, last_active_at=(now - timedelta(minutes=5)).isoformat())
    output: list[str] = []

    selected = choose_resume_session(
        registry,
        explicit_ref=None,
        max_age_days=7,
        project_scoped=True,
        picker_on_ambiguous=True,
        input_func=lambda _prompt: "2",
        output_func=output.append,
    )

    assert selected is not None
    assert selected.session_id == older_id
    assert any("Found previous FCC sessions" in line for line in output)


def test_picker_defaults_latest_on_eof(tmp_path: Path) -> None:
    registry = SessionRegistry(tmp_path)
    latest_id, _ = _create_resumable_session(
        registry,
        tmp_path,
        native_id="latest-eof",
        name="latest-task",
    )
    _create_resumable_session(
        registry,
        tmp_path,
        native_id="older-eof",
        name="older-task",
    )
    now = datetime.now(UTC)
    registry.update(latest_id, last_active_at=now.isoformat())

    selected = choose_resume_session(
        registry,
        explicit_ref=None,
        max_age_days=7,
        project_scoped=True,
        picker_on_ambiguous=True,
        input_func=lambda _prompt: (_ for _ in ()).throw(EOFError),
        output_func=lambda _line: None,
    )

    assert selected is not None
    assert selected.session_id == latest_id


def test_sessions_table_output_is_compact(tmp_path: Path) -> None:
    registry = SessionRegistry(tmp_path)
    session_id, _ = _create_resumable_session(registry, tmp_path)

    table = format_sessions_table(registry.list_recent(limit=1))

    assert "Status" in table
    assert "Last Active" in table
    assert "deepseek-v4-pro" in table
    assert "fix-auth-middleware" in table
    assert session_id in table


def test_session_doctor_migrates_and_fixes_safe_state(tmp_path: Path) -> None:
    db_path = tmp_path / ".fcc" / "sessions.sqlite"
    db_path.parent.mkdir(parents=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE sessions (name TEXT, status TEXT)")
        conn.execute(
            "INSERT INTO sessions(name, status) VALUES ('legacy-task', 'active')"
        )

    registry = SessionRegistry(tmp_path)
    record = registry.list_recent(limit=1)[0]
    missing_transcript = tmp_path / "missing.jsonl"
    registry.update(
        record.session_id,
        pid=424242,
        last_heartbeat_at=(datetime.now(UTC) - timedelta(hours=1)).isoformat(),
        transcript_path=str(missing_transcript),
    )

    with patch("cli.session_registry.process_is_running", return_value=False):
        report = registry.doctor()

    fixed = registry.get(record.session_id)
    assert report["registry_exists"] is True
    assert report["handoff_exists"] is True
    assert report["healed_active_sessions"] == 1
    assert fixed is not None
    assert fixed.status == "missing_transcript"
    assert (tmp_path / ".fcc" / "context" / "handoff.md").is_file()


def test_session_registry_rebuilds_all_columns_without_primary_key(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / ".fcc" / "sessions.sqlite"
    db_path.parent.mkdir(parents=True)
    column_defs = ", ".join(f"{name} TEXT" for name in SESSION_COLUMNS)
    with sqlite3.connect(db_path) as conn:
        conn.execute(f"CREATE TABLE sessions ({column_defs})")
        conn.execute(
            """
            INSERT INTO sessions(session_id, project_root, cwd, status, started_at, last_active_at)
            VALUES ('legacy-id', ?, ?, 'resumable', ?, ?)
            """,
            (
                str(tmp_path),
                str(tmp_path),
                datetime.now(UTC).isoformat(),
                datetime.now(UTC).isoformat(),
            ),
        )

    registry = SessionRegistry(tmp_path)
    record = registry.create_terminal_session(
        cwd=tmp_path,
        command=["claude"],
        provider="deepseek",
        model="deepseek/deepseek-v4-pro",
    )

    assert registry.get(record.session_id) is not None


def test_discover_latest_transcript_prefers_exact_native_id(
    tmp_path: Path,
) -> None:
    claude_projects = tmp_path / ".claude" / "projects" / "project"
    claude_projects.mkdir(parents=True)
    exact = claude_projects / "expected.jsonl"
    exact.write_text(
        json.dumps({"sessionId": "expected", "cwd": str(tmp_path)}),
        encoding="utf-8",
    )
    old_time = (datetime.now(UTC) - timedelta(hours=1)).timestamp()
    os.utime(exact, (old_time, old_time))
    for index in range(30):
        newer = claude_projects / f"newer-{index}.jsonl"
        newer.write_text(
            json.dumps({"sessionId": f"newer-{index}", "cwd": str(tmp_path / "other")}),
            encoding="utf-8",
        )

    with patch("pathlib.Path.home", return_value=tmp_path):
        found = discover_latest_transcript(
            project_root=tmp_path,
            cwd=tmp_path,
            started_at=datetime.now(UTC).isoformat(),
            native_session_id="expected",
        )

    assert found is not None
    assert found.path == exact


def test_discover_latest_transcript_does_not_fallback_cross_project(
    tmp_path: Path,
) -> None:
    claude_projects = tmp_path / ".claude" / "projects" / "project"
    claude_projects.mkdir(parents=True)
    other = claude_projects / "other.jsonl"
    other.write_text(
        json.dumps({"sessionId": "other", "cwd": str(tmp_path / "other-project")}),
        encoding="utf-8",
    )

    with patch("pathlib.Path.home", return_value=tmp_path):
        found = discover_latest_transcript(
            project_root=tmp_path / "project-a",
            cwd=tmp_path / "project-a",
            started_at=datetime.now(UTC).isoformat(),
        )

    assert found is None


def test_bad_explicit_resume_ref_exits(tmp_path: Path) -> None:
    from cli.entrypoints import launch_claude

    with (
        patch("cli.entrypoints.get_settings", return_value=_settings()),
        patch("cli.entrypoints._preflight_proxy", return_value=None),
        patch("cli.entrypoints.shutil.which", return_value="claude"),
        patch("cli.entrypoints.maybe_update_claude_code"),
        patch("cli.entrypoints.subprocess.Popen") as popen,
        pytest.raises(SystemExit) as exc_info,
    ):
        launch_claude([str(tmp_path)], resume_ref="missing-session")

    assert str(exc_info.value) == "FCC session not found: missing-session"
    popen.assert_not_called()


def test_native_resume_flag_forms_disable_auto_resume() -> None:
    from cli.entrypoints import _args_request_native_resume

    assert _args_request_native_resume(["--resume=abc"]) is True
    assert _args_request_native_resume(["--session-id=abc"]) is True


def test_fcc_sessions_list_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from cli import fcc_cli

    monkeypatch.chdir(tmp_path)
    registry = SessionRegistry(tmp_path)
    _create_resumable_session(registry, tmp_path)

    fcc_cli.main(["sessions", "list"])

    captured = capsys.readouterr()
    assert "fix-auth-middleware" in captured.out
    assert "resumable" in captured.out


def test_continuity_prompt_uses_handoff_not_raw_transcript(tmp_path: Path) -> None:
    context_dir = tmp_path / ".fcc" / "context"
    context_dir.mkdir(parents=True)
    (context_dir / "handoff.md").write_text(
        "# FCC Handoff\n\n## Current State\n- Continue compactly.\n",
        encoding="utf-8",
    )
    raw_transcript = tmp_path / "raw.jsonl"
    raw_transcript.write_text("RAW OLD TRANSCRIPT SHOULD STAY OUT", "utf-8")
    registry = SessionRegistry(tmp_path)
    record = registry.create_terminal_session(
        cwd=tmp_path,
        command=["claude"],
        provider="deepseek",
        model="deepseek/deepseek-v4-pro",
    )
    registry.update(record.session_id, transcript_path=str(raw_transcript))

    prompt = build_continuity_prompt(tmp_path, record)

    assert "Continue compactly" in prompt
    assert "RAW OLD TRANSCRIPT" not in prompt
