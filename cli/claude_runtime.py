"""Shared Claude Code runtime environment and update helpers."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from loguru import logger

from config.paths import config_dir_path

CLAUDE_CODE_AUTO_COMPACT_WINDOW = "1000000"
CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY = "1"
CLAUDE_CODE_PACKAGE_MANAGER_AUTO_UPDATE = "1"
CLAUDE_CODE_UPDATE_INTERVAL_SECONDS = 24 * 60 * 60

_CLAUDE_CODE_NPM_PACKAGE = "@anthropic-ai/claude-code"
_UPDATE_STATE_FILE = "claude-code-update.json"


def apply_claude_code_runtime_env(env: dict[str, str]) -> None:
    """Apply FCC's Claude Code runtime defaults in-place."""
    env["CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY"] = (
        CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY
    )
    env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = CLAUDE_CODE_AUTO_COMPACT_WINDOW
    env["CLAUDE_CODE_PACKAGE_MANAGER_AUTO_UPDATE"] = (
        CLAUDE_CODE_PACKAGE_MANAGER_AUTO_UPDATE
    )


def maybe_update_claude_code(
    claude_command: str,
    *,
    force: bool = False,
    timeout_seconds: int = 180,
) -> None:
    """Best-effort, throttled update of the same Claude Code CLI FCC launches."""
    if os.environ.get("FCC_SKIP_CLAUDE_CODE_UPDATE") == "1" and not force:
        return
    resolved = shutil.which(claude_command) or claude_command
    state_path = config_dir_path() / _UPDATE_STATE_FILE
    state_key = _state_key(resolved)
    if not force and not _update_due(state_path, state_key):
        return

    command = _update_command_for_install(resolved)
    env = os.environ.copy()
    apply_claude_code_runtime_env(env)

    outcome = "ok"
    try:
        completed = subprocess.run(
            command,
            check=False,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        if completed.returncode != 0:
            outcome = f"exit-{completed.returncode}"
            logger.warning(
                "Claude Code update check failed: command={} returncode={} stderr_chars={}",
                command[0],
                completed.returncode,
                len(completed.stderr or ""),
            )
    except (subprocess.SubprocessError, OSError) as exc:
        outcome = type(exc).__name__
        logger.warning(
            "Claude Code update check failed: command={} error={}",
            command[0],
            type(exc).__name__,
        )
    finally:
        try:
            _write_update_state(state_path, state_key, resolved, outcome)
        except OSError:
            logger.warning("Claude Code update state could not be written.")


def _update_command_for_install(resolved_claude: str) -> list[str]:
    npm = shutil.which("npm")
    if npm is not None and _resolved_path_is_under_npm_prefix(resolved_claude, npm):
        return [
            npm,
            "install",
            "-g",
            f"{_CLAUDE_CODE_NPM_PACKAGE}@latest",
        ]
    return [resolved_claude, "update"]


def _resolved_path_is_under_npm_prefix(resolved_claude: str, npm_command: str) -> bool:
    try:
        completed = subprocess.run(
            [npm_command, "prefix", "-g"],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except subprocess.SubprocessError, OSError:
        return False

    if completed.returncode != 0:
        return False
    prefix = completed.stdout.strip()
    if not prefix:
        return False

    try:
        resolved_path = Path(resolved_claude).resolve()
        prefix_path = Path(prefix).resolve()
        return resolved_path == prefix_path or prefix_path in resolved_path.parents
    except OSError:
        return False


def _update_due(state_path: Path, state_key: str) -> bool:
    state = _read_update_state(state_path)
    raw_last_attempt = state.get(state_key, {}).get("last_attempt")
    if not isinstance(raw_last_attempt, int | float):
        return True
    return time.time() - raw_last_attempt >= CLAUDE_CODE_UPDATE_INTERVAL_SECONDS


def _read_update_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if isinstance(data, dict):
        return data
    return {}


def _write_update_state(
    path: Path,
    state_key: str,
    resolved_claude: str,
    outcome: str,
) -> None:
    data = _read_update_state(path)
    data[state_key] = {
        "last_attempt": time.time(),
        "resolved_claude": resolved_claude,
        "outcome": outcome,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _state_key(resolved_claude: str) -> str:
    return hashlib.sha256(str(Path(resolved_claude)).encode()).hexdigest()[:16]
