"""Tests for debugger report schema models."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.debugger.report import (
    DebugReport,
    DebugReportMeta,
    Finding,
    FixEntry,
    FixReport,
    now_iso,
)


def test_finding_roundtrip() -> None:
    finding = Finding(
        id="C1",
        severity="high",
        file="app.py",
        line=42,
        description="Missing input validation",
        evidence="x = request.args['user']",
        suggested_fix="Use request.args.get('user')",
    )
    data = finding.model_dump()
    roundtripped = Finding.model_validate(data)
    assert roundtripped == finding


def test_finding_optional_line() -> None:
    finding = Finding(
        id="P1",
        severity="low",
        file="README.md",
        description="Typos in docs",
        evidence='print("helo")',
        suggested_fix='print("hello")',
    )
    assert finding.line is None
    data = finding.model_dump()
    roundtripped = Finding.model_validate(data)
    assert roundtripped.line is None
    assert roundtripped == finding


def test_debug_report_roundtrip() -> None:
    finding = Finding(
        id="C1",
        severity="high",
        file="app.py",
        line=10,
        description="Unhandled exception",
        evidence="raise Exception",
        suggested_fix="Add try/except",
    )
    meta = DebugReportMeta(risk_level="high")
    report = DebugReport(
        task_name="task-1",
        analyzed_at=now_iso(),
        files_changed=["app.py"],
        correctness=[finding],
        meta=meta,
    )
    data = report.model_dump()
    roundtripped = DebugReport.model_validate(data)
    assert roundtripped.task_name == report.task_name
    assert roundtripped.correctness == report.correctness


def test_debug_report_meta_synced() -> None:
    f1 = Finding(
        id="H1",
        severity="high",
        file="a.py",
        line=1,
        description="High severity",
        evidence="bug",
        suggested_fix="fix it",
    )
    f2 = Finding(
        id="M1",
        severity="medium",
        file="b.py",
        line=2,
        description="Medium severity",
        evidence="bug2",
        suggested_fix="fix it too",
    )
    f3 = Finding(
        id="L1",
        severity="low",
        file="c.py",
        line=3,
        description="Low severity",
        evidence="nit",
        suggested_fix="tidy",
    )
    report = DebugReport(
        task_name="task-2",
        analyzed_at=now_iso(),
        correctness=[f1],
        completeness=[f2],
        process=[f3],
        meta=DebugReportMeta(risk_level="medium"),
    )
    assert report.meta.total_findings == 3
    assert report.meta.fix_priority == ["H1", "M1", "L1"]


def test_debug_report_empty_risk_downgrade() -> None:
    report = DebugReport(
        task_name="task-3",
        analyzed_at=now_iso(),
        meta=DebugReportMeta(risk_level="high"),
    )
    assert report.meta.risk_level == "low"
    assert report.meta.total_findings == 0
    assert report.meta.fix_priority == []
    assert report.is_empty() is True


def test_debug_report_risk_level_values() -> None:
    with pytest.raises(ValidationError):
        DebugReportMeta.model_validate({"risk_level": "critical"})


def test_debug_report_file_roundtrip(tmp_path: Path) -> None:
    finding = Finding(
        id="F1",
        severity="medium",
        file="x.py",
        description="Something",
        evidence="code",
        suggested_fix="fix",
    )
    report = DebugReport(
        task_name="task-4",
        analyzed_at=now_iso(),
        correctness=[finding],
        meta=DebugReportMeta(risk_level="low"),
    )
    file_path = tmp_path / "report.json"
    report.to_path(file_path)
    loaded = DebugReport.from_path(file_path)
    assert loaded.task_name == report.task_name
    assert loaded.correctness == report.correctness


def test_fix_report_roundtrip() -> None:
    entry = FixEntry(
        finding_id="C1",
        action="Added input validation",
        verified=True,
        commit="abc123",
    )
    fix_report = FixReport(
        task_name="task-5",
        debug_report="path/to/debug.json",
        fixed_at=now_iso(),
        fixes_applied=[entry],
        worktree_branch="fix/C1-validation",
    )
    data = fix_report.model_dump()
    roundtripped = FixReport.model_validate(data)
    assert roundtripped.task_name == fix_report.task_name
    assert roundtripped.fixes_applied == fix_report.fixes_applied


def test_fix_report_file_roundtrip(tmp_path: Path) -> None:
    entry = FixEntry(
        finding_id="P1",
        action="Fixed typo in docs",
        verified=False,
    )
    fix_report = FixReport(
        task_name="task-6",
        debug_report="path/to/debug.json",
        fixed_at=now_iso(),
        fixes_skipped=[entry],
    )
    file_path = tmp_path / "fix_report.json"
    fix_report.to_path(file_path)
    loaded = FixReport.from_path(file_path)
    assert loaded.task_name == fix_report.task_name
    assert loaded.fixes_skipped == fix_report.fixes_skipped


def test_now_iso_is_string() -> None:
    ts = now_iso()
    assert isinstance(ts, str)
    # Must be a valid ISO 8601 UTC string: ends with "+00:00" or "Z"
    assert re.search(r"(\+00:00|Z)$", ts)
    # Must parse as a valid datetime
    from datetime import datetime

    ts_clean = ts.replace("Z", "+00:00")
    dt = datetime.fromisoformat(ts_clean)
    assert dt is not None
