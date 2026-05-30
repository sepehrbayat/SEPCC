"""User-facing FCC terminal command facade."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from cli.context_doctor import run_agent_runtime_doctor
from cli.entrypoints import launch_claude
from cli.session_registry import SessionRegistry, resolve_project_root
from cli.session_resume import doctor_report_text, format_sessions_table


def main(argv: Sequence[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        launch_claude([])
        return

    command = args[0]
    if command == "resume":
        _resume(args[1:])
        return
    if command == "sessions":
        _sessions(args[1:])
        return
    if command == "context":
        _context(args[1:])
        return
    launch_claude(args)


def _resume(args: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="fcc resume")
    parser.add_argument("session", nargs="?")
    parsed = parser.parse_args(args)
    launch_claude([], resume_ref=parsed.session, auto_resume=parsed.session is None)


def _sessions(args: list[str]) -> None:
    if not args:
        args = ["list"]
    command = args[0]
    registry = SessionRegistry(resolve_project_root(Path.cwd()))

    if command == "list":
        records = registry.list_recent(limit=20)
        print(format_sessions_table(records))
        return
    if command == "last":
        records = registry.list_recent(limit=1)
        print(format_sessions_table(records))
        return
    if command == "clean":
        registry.heal_stale_active_sessions()
        removed = registry.clean()
        print(f"Cleaned {removed} closed session(s).")
        return
    if command == "doctor":
        report = {
            **registry.doctor(),
            **run_agent_runtime_doctor(registry.project_root),
        }
        print(doctor_report_text(report))
        return
    if command == "rename":
        _rename_session(registry, args[1:])
        return

    raise SystemExit(f"Unknown fcc sessions command: {command}")


def _context(args: list[str]) -> None:
    if not args:
        args = ["doctor"]
    command = args[0]
    root = resolve_project_root(Path.cwd())
    if command == "doctor":
        print(doctor_report_text(run_agent_runtime_doctor(root)))
        return
    raise SystemExit(f"Unknown fcc context command: {command}")


def _rename_session(registry: SessionRegistry, args: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="fcc sessions rename")
    parser.add_argument("session")
    parser.add_argument("name")
    parsed = parser.parse_args(args)
    record = registry.resolve(parsed.session)
    if record is None:
        raise SystemExit(f"Session not found: {parsed.session}")
    registry.rename(record.session_id, parsed.name)
    print(f"Renamed {record.session_id} to {parsed.name}")


if __name__ == "__main__":
    main()
