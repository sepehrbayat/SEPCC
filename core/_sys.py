"""Shared OS-level and text utilities for the FCC package family.

Both ``core/`` and ``cli/`` packages import from here — this is the
canonical home for functions that would otherwise be duplicated across
the import-boundary line.
"""

from __future__ import annotations

import os
import subprocess

# ── Process liveness ─────────────────────────────────────────────────


def process_is_running(pid: int) -> bool:
    """Return ``True`` when the process identified by *pid* is running.

    Works on Windows (via ``tasklist``) and Unix (via ``os.kill`` with
    signal 0).
    """
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


# ── Slugification ────────────────────────────────────────────────────


def slugify_text(
    text: str | None,
    *,
    max_words: int = 5,
    fallback: str | None = None,
) -> str | None:
    """Convert *text* into a filesystem-safe lowercase slug.

    Parameters
    ----------
    max_words:
        Maximum number of words (alphanumeric clusters > 2 chars) to include.
    fallback:
        Value to return when no valid words are found.  ``None`` means
        ``None``; set to a string (e.g. ``"task"``) for a guaranteed result.
    """
    if not text:
        return fallback

    words: list[str] = []
    for raw in text.lower().replace("_", "-").split():
        cleaned = "".join(ch for ch in raw if ch.isalnum() or ch == "-").strip("-")
        if cleaned:
            words.append(cleaned)
        if len(words) >= max_words:
            break

    if not words:
        return fallback
    return "-".join(words)[:64]
