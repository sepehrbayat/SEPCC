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


def test_stop_existing_server_script_only_targets_sepcc_fcc_server() -> None:
    text = _windows_script_text("stop-fcc-server-on-port.ps1")

    assert "Get-NetTCPConnection -LocalPort $Port -State Listen" in text
    assert "Test-IsSepccServer" in text
    assert 'IndexOf("fcc-server"' in text
    assert "IndexOf($RepoRoot" in text
    assert "Stop-Process -Id $serverPid -Force" in text
