"""Terminal resume planning and CLI presentation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.context.sqlite_store import SQLiteContextStore
from core.context.summarizer import compact_lines, extract_section

from .session_registry import (
    DEFAULT_HANDOFF_RELATIVE,
    SessionRegistry,
    TerminalSessionRecord,
    discover_latest_transcript,
    parse_timestamp,
)

COMPACT_RESUME_MAX_CHARS = 2600


@dataclass(frozen=True, slots=True)
class ResumePlan:
    session: TerminalSessionRecord | None
    use_native_resume: bool
    native_session_id: str | None
    continuity_prompt: str | None
    parent_session_id: str | None = None


def choose_resume_session(
    registry: SessionRegistry,
    *,
    explicit_ref: str | None,
    max_age_days: int,
    project_scoped: bool,
    picker_on_ambiguous: bool,
    input_func=input,
    output_func=print,
) -> TerminalSessionRecord | None:
    """Resolve an explicit or auto-selected session for launch."""
    registry.heal_stale_active_sessions()
    if explicit_ref:
        return registry.resolve(explicit_ref, project_scoped=project_scoped)

    candidates = registry.resumable_for_project(
        limit=20,
        max_age_days=max_age_days,
        project_scoped=project_scoped,
    )
    if not candidates:
        return None
    if len(candidates) == 1 or not picker_on_ambiguous:
        return candidates[0]
    return _pick_session(candidates, input_func=input_func, output_func=output_func)


def build_resume_plan(
    registry: SessionRegistry,
    session: TerminalSessionRecord | None,
) -> ResumePlan:
    """Create a native-resume or compact-continuity launch plan."""
    if session is None:
        return ResumePlan(
            session=None,
            use_native_resume=False,
            native_session_id=None,
            continuity_prompt=None,
        )
    if (
        session.native_session_id
        and session.transcript_path
        and Path(session.transcript_path).is_file()
    ):
        return ResumePlan(
            session=session,
            use_native_resume=True,
            native_session_id=session.native_session_id,
            continuity_prompt=None,
        )
    if session.native_session_id:
        rediscovered = discover_latest_transcript(
            project_root=registry.project_root,
            cwd=Path(session.cwd),
            started_at=session.started_at,
            native_session_id=session.native_session_id,
        )
        if rediscovered is not None:
            registry.update(
                session.session_id,
                native_session_id=rediscovered.native_session_id,
                transcript_path=str(rediscovered.path),
            )
            return ResumePlan(
                session=session,
                use_native_resume=True,
                native_session_id=rediscovered.native_session_id,
                continuity_prompt=None,
            )
    registry.mark_missing_transcript(session.session_id)
    return ResumePlan(
        session=session,
        use_native_resume=False,
        native_session_id=None,
        continuity_prompt=build_continuity_prompt(registry.project_root, session),
        parent_session_id=session.session_id,
    )


def build_continuity_prompt(
    project_root: Path,
    session: TerminalSessionRecord,
    *,
    max_chars: int = COMPACT_RESUME_MAX_CHARS,
) -> str:
    """Build compact resume context without replaying raw transcripts."""
    handoff_path = Path(session.handoff_path or project_root / DEFAULT_HANDOFF_RELATIVE)
    handoff = _read_text(handoff_path)
    current_state = extract_section(handoff, "Current State")
    decisions = extract_section(handoff, "Decisions")
    next_steps = extract_section(handoff, "Next Steps")
    must_not_forget = extract_section(handoff, "Must Not Forget")
    snippets = _memory_snippets(project_root, session)
    parts = [
        "FCC compact resume context. Do not replay raw transcripts.",
        "",
        "Previous goal:",
        f"- {session.current_task_title or session.name or 'Resume prior FCC terminal session.'}",
        "",
        "Last known state:",
        compact_lines(
            current_state or session.last_response_excerpt or "", max_lines=5
        ),
        "",
        "Completed steps / decisions:",
        compact_lines(decisions, max_lines=5),
        "",
        "Known blockers / must not forget:",
        compact_lines(must_not_forget, max_lines=5),
        "",
        "Next recommended action:",
        compact_lines(next_steps or "- Continue from the last handoff.", max_lines=4),
        "",
        "Verification commands:",
        "- uv run ruff format",
        "- uv run ruff check",
        "- uv run ty check",
        "- uv run pytest",
    ]
    if snippets:
        parts.extend(["", "Relevant memory snippets:", *snippets])
    return compact_lines("\n".join(parts), max_lines=36, max_chars=max_chars)


def format_sessions_table(records: list[TerminalSessionRecord]) -> str:
    """Return a compact terminal table."""
    headers = ("Status", "Last Active", "Model", "Name", "ID")
    rows = [
        (
            record.display_status,
            _display_time(record.last_active_at),
            _short_model(record.model),
            record.display_name,
            record.session_id,
        )
        for record in records
    ]
    widths = [
        max(len(headers[index]), *(len(row[index]) for row in rows))
        if rows
        else len(headers[index])
        for index in range(len(headers))
    ]
    lines = [
        "  ".join(header.ljust(widths[index]) for index, header in enumerate(headers))
    ]
    lines.extend(
        "  ".join(value.ljust(widths[index]) for index, value in enumerate(row))
        for row in rows
    )
    return "\n".join(lines)


def doctor_report_text(report: dict[str, Any]) -> str:
    lines = ["FCC session doctor:"]
    for key, value in report.items():
        lines.append(f"- {key}: {value}")
    return "\n".join(lines)


def _pick_session(
    candidates: list[TerminalSessionRecord],
    *,
    input_func,
    output_func,
) -> TerminalSessionRecord | None:
    output_func("Found previous FCC sessions for this project:\n")
    for index, record in enumerate(candidates, start=1):
        output_func(
            f"{index}. {_display_time(record.last_active_at)}  "
            f"{_short_model(record.model)}  {record.display_name}"
        )
    try:
        choice = input_func(
            "\nPress Enter to resume latest, type number, or type n for new session: "
        ).strip()
    except EOFError:
        return candidates[0]
    if not choice:
        return candidates[0]
    if choice.lower() == "n":
        return None
    if choice.isdigit():
        index = int(choice) - 1
        if 0 <= index < len(candidates):
            return candidates[index]
    return candidates[0]


def _memory_snippets(project_root: Path, session: TerminalSessionRecord) -> list[str]:
    query = " ".join(
        part
        for part in (
            session.current_task_title,
            session.name,
            session.last_prompt_excerpt,
        )
        if part
    )
    if not query:
        return []
    db_path = project_root / ".fcc" / "indexes" / "context.sqlite"
    if not db_path.is_file():
        return []
    results = SQLiteContextStore(db_path).search(query, limit=3)
    return [f"- {result.source}: {result.snippet}" for result in results]


def _read_text(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _display_time(value: str) -> str:
    parsed = parse_timestamp(value)
    if parsed is None:
        return value[:16]
    return parsed.astimezone().strftime("%Y-%m-%d %H:%M")


def _short_model(model: str | None) -> str:
    if not model:
        return "-"
    return model.split("/", 1)[1] if "/" in model else model
