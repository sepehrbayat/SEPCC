from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch


def test_maybe_update_claude_code_uses_npm_for_npm_owned_binary(tmp_path: Path) -> None:
    from cli import claude_runtime

    npm_bin = tmp_path / "npm"
    claude_bin = tmp_path / "claude"
    npm_bin.write_text("", encoding="utf-8")
    claude_bin.write_text("", encoding="utf-8")
    run_calls: list[list[str]] = []

    def fake_run(command, **_kwargs):
        run_calls.append(list(command))
        if command[1:3] == ["prefix", "-g"]:
            return MagicMock(returncode=0, stdout=str(tmp_path), stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")

    def fake_which(command: str) -> str | None:
        if command == "npm":
            return str(npm_bin)
        return None

    with (
        patch.object(claude_runtime, "config_dir_path", return_value=tmp_path / ".fcc"),
        patch.object(claude_runtime.shutil, "which", side_effect=fake_which),
        patch.object(claude_runtime.subprocess, "run", side_effect=fake_run),
    ):
        claude_runtime.maybe_update_claude_code(str(claude_bin), force=True)

    assert run_calls[-1] == [
        str(npm_bin),
        "install",
        "-g",
        "@anthropic-ai/claude-code@latest",
    ]


def test_maybe_update_claude_code_uses_claude_update_for_non_npm_binary(
    tmp_path: Path,
) -> None:
    from cli import claude_runtime

    claude_bin = tmp_path / "native" / "claude"
    claude_bin.parent.mkdir()
    claude_bin.write_text("", encoding="utf-8")
    run_calls: list[list[str]] = []

    def fake_run(command, **_kwargs):
        run_calls.append(list(command))
        if command[1:3] == ["prefix", "-g"]:
            return MagicMock(returncode=0, stdout=str(tmp_path / "npm"), stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")

    def fake_which(command: str) -> str | None:
        if command == "npm":
            return str(tmp_path / "npm")
        return None

    with (
        patch.object(claude_runtime, "config_dir_path", return_value=tmp_path / ".fcc"),
        patch.object(claude_runtime.shutil, "which", side_effect=fake_which),
        patch.object(claude_runtime.subprocess, "run", side_effect=fake_run),
    ):
        claude_runtime.maybe_update_claude_code(str(claude_bin), force=True)

    assert run_calls[-1] == [str(claude_bin), "update"]


def test_maybe_update_claude_code_is_throttled(tmp_path: Path) -> None:
    from cli import claude_runtime

    claude_bin = tmp_path / "claude"
    claude_bin.write_text("", encoding="utf-8")

    with (
        patch.object(claude_runtime, "config_dir_path", return_value=tmp_path / ".fcc"),
        patch.object(claude_runtime.shutil, "which", return_value=None),
        patch.object(claude_runtime.subprocess, "run") as run,
    ):
        run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        claude_runtime.maybe_update_claude_code(str(claude_bin), force=True)
        claude_runtime.maybe_update_claude_code(str(claude_bin))

    assert run.call_count == 1
