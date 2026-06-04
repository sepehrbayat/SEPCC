"""Inject compact project context at Claude Code session start."""

from __future__ import annotations

from _shared import (
    compact_lines,
    emit_hook_json,
    project_root,
    read_hook_input,
    read_text,
    run_hook,
    runtime_contract,
    startup_command_hint,
)


def _graph_context(root: object) -> str:
    """Build graph structural summary, if available."""
    try:
        from core.graph import load_graph
        from core.graph.context import build_session_bootstrap
        from core.graph.query import GraphQuery
    except ImportError:
        return ""
    from pathlib import Path

    if not isinstance(root, Path):
        return ""
    graph_json = root / ".fcc" / "graph" / "graph.json"
    if not graph_json.is_file():
        return ""  # No graph installed — normal, not an error
    try:
        store = load_graph(root)
        query = GraphQuery(store)
        changed_files = _changed_files(root)
        return build_session_bootstrap(query, changed_files=changed_files)
    except Exception as exc:
        return (
            f"## Graph Context\nGraph context unavailable ({type(exc).__name__}). "
            "Rebuild with: fcc-bootstrap-context --install-graphify"
        )


def _changed_files(root) -> list[str]:
    """Return list of files changed since last commit, or empty list on failure."""
    import subprocess
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            capture_output=True, text=True, timeout=5,
            cwd=str(root),
        )
        if result.returncode == 0:
            return [f.strip() for f in result.stdout.splitlines() if f.strip()]
    except (OSError, subprocess.SubprocessError):
        pass
    return []


def main() -> None:
    data = read_hook_input()
    root = project_root(data)
    sections: list[str] = [
        f"## .fcc/context/agent-runtime.md\n{runtime_contract(root)}"
    ]
    command_hint = startup_command_hint(root)
    if command_hint:
        sections.append(f"## Command Protocol\n{command_hint}")
    for rel_path in (
        "CLAUDE.md",
        "CLAUDE.local.md",
        ".fcc/context/handoff.md",
        ".fcc/context/quality-gates.md",
    ):
        content = compact_lines(read_text(root / rel_path), max_lines=12, max_chars=900)
        if content:
            sections.append(f"## {rel_path}\n{content}")

    graph_context = _graph_context(root)
    if graph_context:
        sections.append(graph_context)

    payload = "FCC project context:\n" + "\n\n".join(sections)
    emit_hook_json("SessionStart", additional_context=payload)


if __name__ == "__main__":
    run_hook("SessionStart", main)
