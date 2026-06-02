"""Read and write deterministic FCC handoff files."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from core.context.summarizer import (
    compact_lines,
    extract_decisions,
    extract_section,
    parse_transcript_text,
    summarize_transcript,
)

CONTEXT_DIR = Path(".fcc") / "context"
FACTS_FILE = CONTEXT_DIR / "facts.md"
DECISIONS_FILE = CONTEXT_DIR / "decisions.md"
HANDOFF_FILE = CONTEXT_DIR / "handoff.md"


def build_handoff(
    *,
    transcript_text: str,
    existing_handoff: str = "",
    facts_text: str = "",
    decisions_text: str = "",
    structural_context: str = "",
) -> str:
    """Build the compact current-state handoff from durable inputs."""
    must_section = extract_section(existing_handoff, "Must Not Forget")
    must_lines = compact_lines(
        "\n".join(part for part in (must_section, facts_text) if part.strip()),
        max_lines=8,
        max_chars=1200,
    )
    if not must_lines:
        must_lines = "- Add project-critical facts to CLAUDE.local.md."

    current_state = "\n".join(summarize_transcript(transcript_text, max_items=5))
    decision_lines = extract_decisions(
        "\n".join(part for part in (transcript_text, decisions_text) if part.strip()),
        max_items=5,
    )
    decisions = "\n".join(decision_lines) or "- No new decisions detected."

    sections = [
        "# FCC Handoff",
        "",
        "## Must Not Forget",
        must_lines,
        "",
        "## Current State",
        current_state,
        "",
    ]

    if structural_context:
        sections.extend([structural_context, "", ""])

    sections.extend([
        "## Decisions",
        decisions,
        "",
        "## Next Steps",
        "- Run /verify-context before major edits.",
        "- Store raw logs in the SQLite sidecar; do not replay them into chat.",
        "",
    ])

    return "\n".join(sections)


def _build_graph_handoff_section(project_root: Path) -> str:
    """Try to build a structural context section from the knowledge graph."""
    try:
        from core.graph import load_graph
        from core.graph.context import build_handoff_context
        from core.graph.query import GraphQuery

        store = load_graph(project_root)
        query = GraphQuery(store)
        return build_handoff_context(query)
    except Exception:
        return ""


def regenerate_handoff(project_root: Path, transcript_path: Path | str | None) -> str:
    """Rewrite `.fcc/context/handoff.md` and append decision deltas."""
    context_dir = project_root / CONTEXT_DIR
    context_dir.mkdir(parents=True, exist_ok=True)

    handoff_path = project_root / HANDOFF_FILE
    facts_path = project_root / FACTS_FILE
    decisions_path = project_root / DECISIONS_FILE

    existing_handoff = _read_text(handoff_path)
    facts_text = _read_text(facts_path)
    decisions_text = _read_text(decisions_path)
    transcript_text = parse_transcript_text(transcript_path)
    structural_context = _build_graph_handoff_section(project_root)
    new_handoff = build_handoff(
        transcript_text=transcript_text,
        existing_handoff=existing_handoff,
        facts_text=facts_text,
        decisions_text=decisions_text,
        structural_context=structural_context,
    )
    handoff_path.write_text(new_handoff, encoding="utf-8")

    decision_updates = extract_decisions(transcript_text, max_items=5)
    if decision_updates:
        _append_new_decisions(decisions_path, decision_updates)
    return new_handoff


def must_not_forget(project_root: Path, *, max_chars: int = 1200) -> str:
    """Return only the handoff's must-not-forget section."""
    handoff = _read_text(project_root / HANDOFF_FILE)
    return compact_lines(
        extract_section(handoff, "Must Not Forget"),
        max_lines=8,
        max_chars=max_chars,
    )


def _append_new_decisions(path: Path, decisions: list[str]) -> None:
    existing = _read_text(path)
    existing_keys = {line.strip().lower() for line in existing.splitlines()}
    new_items = [
        item for item in decisions if item.strip().lower() not in existing_keys
    ]
    if not new_items:
        return
    stamp = datetime.now(UTC).date().isoformat()
    prefix = "" if existing.endswith("\n") or not existing else "\n"
    block = "\n".join([f"{prefix}## {stamp}", *new_items, ""])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(block)


def _read_text(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")
