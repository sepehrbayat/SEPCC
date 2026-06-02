from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _windows_script_text(name: str) -> str:
    return (_repo_root() / "scripts" / "windows" / name).read_text(encoding="utf-8")


def test_launch_shortcut_stops_existing_server_before_starting_new_one() -> None:
    text = _windows_script_text("launch-fcc-claude.cmd")

    stop_call = "stop-fcc-server-on-port.ps1"
    start_call = 'start "SEPCC Server"'

    assert stop_call in text
    assert text.index(stop_call) < text.index(start_call)
    assert '-Port "%FCC_PORT%" -Repo "%FCC_REPO%"' in text


def test_launch_shortcut_does_not_lock_sepcc_console_scripts() -> None:
    text = _windows_script_text("launch-fcc-claude.cmd")

    assert "run-entrypoint.py" in text
    assert "uv run --no-sync python" in text
    assert "uv run fcc-server" not in text
    assert "uv run fcc-claude" not in text
    assert "uv run fcc-bootstrap-context" not in text


def test_launch_shortcut_tries_sync_before_no_sync_fallback() -> None:
    text = _windows_script_text("launch-fcc-claude.cmd")

    sync_check = 'uv run python "%FCC_REPO%\\scripts\\windows\\run-entrypoint.py" check'
    no_sync_check = (
        'uv run --no-sync python "%FCC_REPO%\\scripts\\windows\\run-entrypoint.py" '
        "check"
    )

    assert sync_check in text
    assert no_sync_check in text
    assert text.index(sync_check) < text.index(no_sync_check)


def test_launch_shortcut_uses_no_sync_for_long_lived_processes() -> None:
    text = _windows_script_text("launch-fcc-claude.cmd")

    assert "run-entrypoint.py serve" in text
    assert "run-entrypoint.py launch" in text
    assert 'start "SEPCC Server"' in text
    assert "uv run --no-sync python scripts\\windows\\run-entrypoint.py serve" in text


def test_launch_shortcut_uses_no_sync_for_project_bootstrap_branches() -> None:
    text = _windows_script_text("launch-fcc-claude.cmd")
    command = (
        'uv run --no-sync python "%FCC_REPO%\\scripts\\windows\\run-entrypoint.py" '
        'bootstrap --target "%FCC_PROJECT%"'
    )

    assert text.count(command) >= 2
    assert 'uv run fcc-bootstrap-context --target "%FCC_PROJECT%"' not in text


def test_launch_shortcut_gets_port_without_project_sync() -> None:
    text = _windows_script_text("launch-fcc-claude.cmd")

    assert (
        'uv run --no-sync python "%FCC_REPO%\\scripts\\windows\\get-fcc-port.py"'
        in text
    )
    assert 'uv run python "%FCC_REPO%\\scripts\\windows\\get-fcc-port.py"' not in text


def test_windows_entrypoint_runner_exists_for_no_sync_launch() -> None:
    text = _windows_script_text("run-entrypoint.py")

    assert "def main()" in text
    assert "launch_claude([args.project])" in text
    assert "serve()" in text
    assert 'bootstrap_main(["--target", args.target])' in text


def test_windows_entrypoint_runner_has_only_known_subcommands() -> None:
    text = _windows_script_text("run-entrypoint.py")

    assert 'subparsers.add_parser("check"' in text
    assert 'subparsers.add_parser("serve"' in text
    assert 'subparsers.add_parser("bootstrap"' in text
    assert 'subparsers.add_parser("launch"' in text
    assert "required=True" in text


def test_stop_existing_server_script_only_targets_sepcc_fcc_server() -> None:
    text = _windows_script_text("stop-fcc-server-on-port.ps1")

    assert "Get-NetTCPConnection -LocalPort $Port -State Listen" in text
    assert "Test-IsSepccServer" in text
    assert 'IndexOf("fcc-server"' in text
    assert 'IndexOf("run-entrypoint.py"' in text
    assert 'IndexOf(" serve"' in text
    assert "IndexOf($RepoRoot" in text
    assert "Stop-Process -Id $serverPid -Force" in text
