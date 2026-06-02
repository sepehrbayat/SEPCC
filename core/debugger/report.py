"""Pydantic data contracts for the FCC agent debugger pipeline.

The debugger subagent produces a ``DebugReport`` after analyzing completed work.
The fixer subagent consumes it and produces a ``FixReport`` with applied fixes.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


def now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(UTC).isoformat()


class Finding(BaseModel):
    """A single issue discovered during debug analysis."""

    id: str
    severity: Literal["high", "medium", "low"]
    file: str
    line: int | None = None
    description: str
    evidence: str
    suggested_fix: str


class DebugReportMeta(BaseModel):
    """Summary metadata extracted from the findings."""

    risk_level: Literal["low", "medium", "high"]
    fix_priority: list[str] = Field(default_factory=list)
    total_findings: int = 0
    tests_passing_before: int | None = None
    tests_total: int | None = None


class DebugReport(BaseModel):
    """Complete debug analysis report produced by the debugger subagent."""

    task_name: str
    analyzed_at: str
    files_changed: list[str] = Field(default_factory=list)
    correctness: list[Finding] = Field(default_factory=list)
    completeness: list[Finding] = Field(default_factory=list)
    process: list[Finding] = Field(default_factory=list)
    meta: DebugReportMeta = Field(default_factory=DebugReportMeta)

    @model_validator(mode="after")
    def sync_meta(self) -> DebugReport:
        """Sync meta.total_findings and meta.fix_priority from the finding lists."""
        all_findings: list[Finding] = (
            self.correctness + self.completeness + self.process
        )

        # Sort by severity priority: high > medium > low
        severity_rank: dict[str, int] = {"high": 3, "medium": 2, "low": 1}
        sorted_findings = sorted(
            all_findings, key=lambda f: severity_rank.get(f.severity, 0), reverse=True
        )

        self.meta.total_findings = len(all_findings)
        self.meta.fix_priority = [f.id for f in sorted_findings]

        # If empty and risk_level is "high", downgrade to "low"
        if not all_findings and self.meta.risk_level == "high":
            self.meta.risk_level = "low"

        return self

    def is_empty(self) -> bool:
        """Return True when there are no findings across all categories."""
        return (
            len(self.correctness) == 0
            and len(self.completeness) == 0
            and len(self.process) == 0
        )

    @classmethod
    def from_path(cls, path: str | Path) -> DebugReport:
        """Deserialize a DebugReport from a JSON file path."""
        raw = Path(path).read_text(encoding="utf-8")
        data = json.loads(raw)
        return cls.model_validate(data)

    def to_path(self, path: str | Path) -> None:
        """Serialize this DebugReport to a JSON file."""
        Path(path).write_text(self.model_dump_json(indent=2), encoding="utf-8")


class FixEntry(BaseModel):
    """A single fix applied (or skipped) by the fixer subagent."""

    finding_id: str
    action: str
    verified: bool = False
    commit: str | None = None


class FixReport(BaseModel):
    """Report produced by the fixer subagent after applying fixes."""

    task_name: str
    debug_report: str
    fixed_at: str
    fixes_applied: list[FixEntry] = Field(default_factory=list)
    fixes_skipped: list[FixEntry] = Field(default_factory=list)
    tests_after: dict[str, Any] | None = None
    worktree_branch: str = ""

    @classmethod
    def from_path(cls, path: str | Path) -> FixReport:
        """Deserialize a FixReport from a JSON file path."""
        raw = Path(path).read_text(encoding="utf-8")
        data = json.loads(raw)
        return cls.model_validate(data)

    def to_path(self, path: str | Path) -> None:
        """Serialize this FixReport to a JSON file."""
        Path(path).write_text(self.model_dump_json(indent=2), encoding="utf-8")
