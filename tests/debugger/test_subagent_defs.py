"""Spec tests for fcc-agent-debugger and fcc-agent-fixer subagent definitions.

Verifies that both subagent definition files contain the required frontmatter
tools and body content described in the debugger pipeline design.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENTS_DIR = REPO_ROOT / ".claude" / "agents"


def _read_agent(name: str) -> str:
    path = AGENTS_DIR / name
    assert path.is_file(), f"Agent file not found: {path}"
    return path.read_text(encoding="utf-8")


def _parse_frontmatter(text: str) -> dict[str, str]:
    match = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    assert match is not None, "No YAML frontmatter found"
    result: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            result[key.strip()] = value.strip()
    return result


# -- Debugger tests ---------------------------------------------------------


def test_debugger_has_required_tools() -> None:
    """fcc-agent-debugger must declare Read, Grep, Glob, Bash in frontmatter tools."""
    content = _read_agent("fcc-agent-debugger.md")
    frontmatter = _parse_frontmatter(content)
    tools = [t.strip() for t in frontmatter.get("tools", "").split(",")]
    for required in ("Read", "Grep", "Glob", "Bash"):
        assert required in tools, f"Missing tool {required!r} in fcc-agent-debugger"


def test_debugger_reads_pending_file() -> None:
    """fcc-agent-debugger must reference .fcc/debugger/pending/ as input source."""
    content = _read_agent("fcc-agent-debugger.md")
    assert ".fcc/debugger/pending/" in content


def test_debugger_writes_report() -> None:
    """fcc-agent-debugger must write output to .fcc/debugger/reports/."""
    content = _read_agent("fcc-agent-debugger.md")
    assert ".fcc/debugger/reports/" in content


def test_debugger_analyzes_all_dimensions() -> None:
    """fcc-agent-debugger must cover Correctness, Completeness, Process Compliance."""
    content = _read_agent("fcc-agent-debugger.md")
    assert "Correctness" in content
    assert "Completeness" in content
    assert "Process Compliance" in content


def test_debugger_id_format_specified() -> None:
    """fcc-agent-debugger must document CORR-, COMP-, PROC- finding ID prefixes."""
    content = _read_agent("fcc-agent-debugger.md")
    assert "CORR-" in content
    assert "COMP-" in content
    assert "PROC-" in content


def test_debugger_must_not_have_write_or_edit() -> None:
    """fcc-agent-debugger is read-only — must NOT declare Write or Edit tools."""
    content = _read_agent("fcc-agent-debugger.md")
    fm = _parse_frontmatter(content)
    tools = fm.get("tools", "")
    tool_list = [t.strip() for t in tools.split(",")]
    assert "Write" not in tool_list, "Debugger must not have Write access"
    assert "Edit" not in tool_list, "Debugger must not have Edit access"


# -- Fixer tests ------------------------------------------------------------


def test_fixer_has_required_tools() -> None:
    """fcc-agent-fixer must declare Read, Write, Edit, Grep, Glob, Bash in frontmatter tools."""
    content = _read_agent("fcc-agent-fixer.md")
    frontmatter = _parse_frontmatter(content)
    tools = [t.strip() for t in frontmatter.get("tools", "").split(",")]
    for required in ("Read", "Write", "Edit", "Grep", "Glob", "Bash"):
        assert required in tools, f"Missing tool {required!r} in fcc-agent-fixer"


def test_fixer_uses_worktree_isolation() -> None:
    """fcc-agent-fixer must use git worktree add and git worktree remove for isolation."""
    content = _read_agent("fcc-agent-fixer.md")
    assert "git worktree add" in content
    assert "git worktree remove" in content


def test_fixer_reads_debug_report() -> None:
    """fcc-agent-fixer must read DebugReports from .fcc/debugger/reports/."""
    content = _read_agent("fcc-agent-fixer.md")
    assert ".fcc/debugger/reports/" in content


def test_fixer_never_touches_main_working_tree() -> None:
    """fcc-agent-fixer must contain an explicit prohibition against modifying the main working tree."""
    content = _read_agent("fcc-agent-fixer.md")
    assert "NEVER modify files in the main working tree" in content


def test_fixer_runs_tests_and_commits() -> None:
    """fcc-agent-fixer must run pytest and git commit after fixing."""
    content = _read_agent("fcc-agent-fixer.md")
    assert "uv run pytest" in content or "pytest" in content
    assert "git commit" in content


def test_fixer_writes_fix_report() -> None:
    """fcc-agent-fixer must write FixReport to .fcc/debugger/fixes/."""
    content = _read_agent("fcc-agent-fixer.md")
    assert ".fcc/debugger/fixes/" in content


def test_fixer_handles_failure_gracefully() -> None:
    """fcc-agent-fixer must document FAILED.md fallback and fixes_skipped support."""
    content = _read_agent("fcc-agent-fixer.md")
    assert "-FAILED.md" in content
    assert "fixes_skipped" in content
