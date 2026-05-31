"""Project-local FCC terminal session registry."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

SESSION_DB_RELATIVE = Path(".fcc") / "sessions.sqlite"
DEFAULT_HANDOFF_RELATIVE = Path(".fcc") / "context" / "handoff.md"
ACTIVE_HEARTBEAT_STALE_SECONDS = 180
CURRENT_SCHEMA_VERSION = 1

SESSION_COLUMNS: dict[str, str] = {
    "session_id": "TEXT PRIMARY KEY",
    "native_session_id": "TEXT",
    "project_root": "TEXT NOT NULL",
    "cwd": "TEXT NOT NULL",
    "name": "TEXT",
    "status": "TEXT NOT NULL",
    "provider": "TEXT",
    "model": "TEXT",
    "transcript_path": "TEXT",
    "handoff_path": "TEXT",
    "parent_session_id": "TEXT",
    "started_at": "TEXT NOT NULL",
    "last_active_at": "TEXT NOT NULL",
    "last_prompt_excerpt": "TEXT",
    "last_response_excerpt": "TEXT",
    "current_task_title": "TEXT",
    "pid": "INTEGER",
    "last_heartbeat_at": "TEXT",
    "terminal_start_at": "TEXT",
    "command": "TEXT",
    "metadata_json": "TEXT",
}

RESUMABLE_STATUSES = {"resumable", "missing_transcript"}


@dataclass(frozen=True, slots=True)
class TerminalSessionRecord:
    session_id: str
    native_session_id: str | None
    project_root: str
    cwd: str
    name: str | None
    status: str
    provider: str | None
    model: str | None
    transcript_path: str | None
    handoff_path: str | None
    parent_session_id: str | None
    started_at: str
    last_active_at: str
    last_prompt_excerpt: str | None
    last_response_excerpt: str | None
    current_task_title: str | None
    pid: int | None
    last_heartbeat_at: str | None
    terminal_start_at: str | None
    command: str | None
    metadata_json: str | None

    @property
    def display_name(self) -> str:
        return self.name or self.current_task_title or "untitled-session"

    @property
    def display_status(self) -> str:
        if self.status == "missing_transcript":
            return "missing"
        return self.status

    def metadata(self) -> dict[str, Any]:
        if not self.metadata_json:
            return {}
        try:
            data = json.loads(self.metadata_json)
        except json.JSONDecodeError:
            return {}
        if isinstance(data, dict):
            return data
        return {}


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def resolve_project_root(cwd: Path) -> Path:
    """Return the nearest project root without requiring git."""
    current = cwd.expanduser().resolve()
    markers = (
        ".fcc",
        ".git",
        "CLAUDE.md",
        "AGENTS.md",
        "pyproject.toml",
        "package.json",
    )
    for candidate in (current, *current.parents):
        if any((candidate / marker).exists() for marker in markers):
            return candidate
    return current


class SessionRegistry:
    """SQLite registry for project-local terminal sessions."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.expanduser().resolve()
        self.db_path = self.project_root / SESSION_DB_RELATIVE
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.migrate()

    def migrate(self) -> None:
        with self._connect() as conn:
            table_exists = (
                conn.execute(
                    """
                    SELECT 1 FROM sqlite_master
                    WHERE type = 'table' AND name = 'sessions'
                    """
                ).fetchone()
                is not None
            )
            if not table_exists:
                conn.execute(_create_sessions_sql(if_not_exists=True))
            table_info = conn.execute("PRAGMA table_info(sessions)").fetchall()
            existing_columns = {row["name"] for row in table_info}
            missing = set(SESSION_COLUMNS) - existing_columns
            if _needs_table_rebuild(table_info, missing):
                self._rebuild_sessions_table(conn)
            else:
                for name in sorted(missing):
                    conn.execute(
                        f"ALTER TABLE sessions ADD COLUMN {name} {SESSION_COLUMNS[name]}"
                    )
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_sessions_project_last_active
                    ON sessions(project_root, last_active_at);
                CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);
                CREATE INDEX IF NOT EXISTS idx_sessions_native_id
                    ON sessions(native_session_id);
                CREATE INDEX IF NOT EXISTS idx_sessions_parent
                    ON sessions(parent_session_id);
                """
            )
            conn.execute(
                """
                INSERT INTO schema_meta(key, value) VALUES ('schema_version', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (str(CURRENT_SCHEMA_VERSION),),
            )

    def _rebuild_sessions_table(self, conn: sqlite3.Connection) -> None:
        """Preserve legacy rows while rebuilding into the current schema."""
        legacy_name = f"sessions_legacy_{int(time.time())}"
        conn.execute(f"ALTER TABLE sessions RENAME TO {legacy_name}")
        conn.execute(_create_sessions_sql(if_not_exists=True))
        legacy_columns = {
            row["name"] for row in conn.execute(f"PRAGMA table_info({legacy_name})")
        }
        rows = conn.execute(f"SELECT * FROM {legacy_name}").fetchall()
        for legacy_row in rows:
            now = utc_now()
            row = _default_session_row(self.project_root, now)
            for column in set(SESSION_COLUMNS) & legacy_columns:
                value = legacy_row[column]
                if value is not None:
                    row[column] = value
            if not row.get("session_id"):
                row["session_id"] = uuid.uuid4().hex[:12]
            if not row.get("project_root"):
                row["project_root"] = str(self.project_root)
            if not row.get("cwd"):
                row["cwd"] = row["project_root"]
            if not row.get("status"):
                row["status"] = "resumable"
            if not row.get("started_at"):
                row["started_at"] = now
            if not row.get("last_active_at"):
                row["last_active_at"] = row["started_at"]
            self._insert_row(conn, row)

    def create_terminal_session(
        self,
        *,
        cwd: Path,
        command: list[str],
        provider: str | None,
        model: str | None,
        name: str | None = None,
        parent_session_id: str | None = None,
        native_session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TerminalSessionRecord:
        session_id = uuid.uuid4().hex[:12]
        now = utc_now()
        handoff_path = self.project_root / DEFAULT_HANDOFF_RELATIVE
        row: dict[str, Any] = {
            "session_id": session_id,
            "native_session_id": native_session_id,
            "project_root": str(self.project_root),
            "cwd": str(cwd.expanduser().resolve()),
            "name": name,
            "status": "active",
            "provider": provider,
            "model": model,
            "transcript_path": None,
            "handoff_path": str(handoff_path),
            "parent_session_id": parent_session_id,
            "started_at": now,
            "last_active_at": now,
            "last_prompt_excerpt": None,
            "last_response_excerpt": None,
            "current_task_title": name,
            "pid": None,
            "last_heartbeat_at": now,
            "terminal_start_at": now,
            "command": " ".join(command),
            "metadata_json": json.dumps(metadata or {}, sort_keys=True),
        }
        self._upsert(row)
        return self.get(session_id) or _record_from_row(row)

    def set_process(self, session_id: str, pid: int) -> None:
        now = utc_now()
        self.update(
            session_id,
            pid=pid,
            status="active",
            last_heartbeat_at=now,
            last_active_at=now,
        )

    def heartbeat(self, session_id: str) -> None:
        now = utc_now()
        self.update(session_id, last_heartbeat_at=now, last_active_at=now)

    def finish_terminal_session(
        self,
        session_id: str,
        *,
        return_code: int | None,
        transcript: TranscriptInfo | None,
    ) -> None:
        updates: dict[str, Any] = {
            "pid": None,
            "last_heartbeat_at": utc_now(),
            "last_active_at": utc_now(),
            "status": "resumable" if return_code == 0 else "failed",
        }
        if transcript is None:
            updates["status"] = "missing_transcript"
        else:
            updates.update(
                {
                    "native_session_id": transcript.native_session_id,
                    "transcript_path": str(transcript.path),
                    "last_prompt_excerpt": transcript.last_prompt_excerpt,
                    "last_response_excerpt": transcript.last_response_excerpt,
                }
            )
            if transcript.generated_name:
                updates["name"] = transcript.generated_name
                updates["current_task_title"] = transcript.generated_name
        self.update(session_id, **updates)

    def mark_missing_transcript(self, session_id: str) -> None:
        self.update(session_id, status="missing_transcript", last_active_at=utc_now())

    def mark_resumable(self, session_id: str) -> None:
        self.update(
            session_id,
            status="resumable",
            pid=None,
            last_heartbeat_at=utc_now(),
            last_active_at=utc_now(),
        )

    def rename(self, session_id: str, name: str) -> None:
        self.update(session_id, name=name, current_task_title=name)

    def update(self, session_id: str, **fields: Any) -> None:
        if not fields:
            return
        unknown = set(fields) - set(SESSION_COLUMNS)
        if unknown:
            raise ValueError(f"Unknown session columns: {', '.join(sorted(unknown))}")
        assignments = ", ".join(f"{key} = ?" for key in fields)
        values = [fields[key] for key in fields]
        values.append(session_id)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE sessions SET {assignments} WHERE session_id = ?",
                values,
            )

    def get(self, session_id: str) -> TerminalSessionRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return _record_from_row(row)

    def resolve(
        self, ref: str, *, project_scoped: bool = True
    ) -> TerminalSessionRecord | None:
        candidates = self.list_recent(limit=100, project_scoped=project_scoped)
        for record in candidates:
            if record.session_id == ref or record.session_id.startswith(ref):
                return record
            if record.native_session_id and (
                record.native_session_id == ref
                or record.native_session_id.startswith(ref)
            ):
                return record
            if record.name == ref:
                return record
        return None

    def list_recent(
        self,
        *,
        limit: int = 20,
        max_age_days: int | None = None,
        project_scoped: bool = True,
        statuses: set[str] | None = None,
    ) -> list[TerminalSessionRecord]:
        clauses: list[str] = []
        params: list[Any] = []
        if project_scoped:
            clauses.append("project_root = ?")
            params.append(str(self.project_root))
        if statuses:
            placeholders = ", ".join("?" for _ in statuses)
            clauses.append(f"status IN ({placeholders})")
            params.extend(sorted(statuses))
        if max_age_days is not None:
            cutoff = datetime.now(UTC) - timedelta(days=max_age_days)
            clauses.append("last_active_at >= ?")
            params.append(cutoff.isoformat())
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM sessions
                {where}
                ORDER BY last_active_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [_record_from_row(row) for row in rows]

    def resumable_for_project(
        self,
        *,
        limit: int = 20,
        max_age_days: int = 7,
        project_scoped: bool = True,
    ) -> list[TerminalSessionRecord]:
        return self.list_recent(
            limit=limit,
            max_age_days=max_age_days,
            project_scoped=project_scoped,
            statuses=RESUMABLE_STATUSES,
        )

    def heal_stale_active_sessions(self) -> int:
        healed = 0
        for record in self.list_recent(
            limit=500, project_scoped=False, statuses={"active"}
        ):
            if _active_session_is_stale(record):
                self.mark_resumable(record.session_id)
                healed += 1
        return healed

    def clean(self, *, closed_older_than_days: int = 30) -> int:
        cutoff = (
            datetime.now(UTC) - timedelta(days=closed_older_than_days)
        ).isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM sessions WHERE status = 'closed' AND last_active_at < ?",
                (cutoff,),
            )
        return int(cursor.rowcount)

    def doctor(self) -> dict[str, Any]:
        self.migrate()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        (self.project_root / DEFAULT_HANDOFF_RELATIVE).parent.mkdir(
            parents=True, exist_ok=True
        )
        healed = self.heal_stale_active_sessions()
        recent = self.list_recent(limit=50)
        missing_transcripts = [
            record.session_id
            for record in recent
            if record.transcript_path and not Path(record.transcript_path).is_file()
        ]
        for session_id in missing_transcripts:
            self.mark_missing_transcript(session_id)

        handoff_path = self.project_root / DEFAULT_HANDOFF_RELATIVE
        (self.project_root / ".fcc" / "indexes").mkdir(parents=True, exist_ok=True)
        missing_handoff = not handoff_path.is_file()
        if missing_handoff:
            handoff_path.write_text(
                "# FCC Handoff\n\n## Must Not Forget\n- Resume from session registry.\n",
                encoding="utf-8",
            )
        hooks_configured = _project_hooks_configured(self.project_root)
        transcript_dir = Path.home() / ".claude" / "projects"
        duplicate_records = self._count_duplicate_native_records()
        return {
            "registry_exists": self.db_path.is_file(),
            "schema_version": CURRENT_SCHEMA_VERSION,
            "native_transcript_dir_reachable": transcript_dir.is_dir(),
            "healed_active_sessions": healed,
            "missing_transcripts_marked": len(missing_transcripts),
            "handoff_exists": handoff_path.is_file(),
            "handoff_recreated": missing_handoff,
            "hooks_configured": hooks_configured,
            "latest_resolvable": bool(self.resumable_for_project(limit=1)),
            "duplicate_records": duplicate_records,
        }

    def _count_duplicate_native_records(self) -> int:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS count FROM (
                    SELECT native_session_id
                    FROM sessions
                    WHERE native_session_id IS NOT NULL
                    GROUP BY native_session_id, project_root
                    HAVING COUNT(*) > 1
                )
                """
            ).fetchone()
        if row is None:
            return 0
        return int(row["count"])

    def _upsert(self, row: dict[str, Any]) -> None:
        columns = list(SESSION_COLUMNS)
        placeholders = ", ".join("?" for _ in columns)
        assignments = ", ".join(
            f"{column} = excluded.{column}"
            for column in columns
            if column != "session_id"
        )
        values = [row.get(column) for column in columns]
        with self._connect() as conn:
            conn.execute(
                f"""
                INSERT INTO sessions({", ".join(columns)})
                VALUES ({placeholders})
                ON CONFLICT(session_id) DO UPDATE SET {assignments}
                """,
                values,
            )

    def _insert_row(self, conn: sqlite3.Connection, row: dict[str, Any]) -> None:
        columns = list(SESSION_COLUMNS)
        placeholders = ", ".join("?" for _ in columns)
        values = [row.get(column) for column in columns]
        conn.execute(
            f"""
            INSERT OR REPLACE INTO sessions({", ".join(columns)})
            VALUES ({placeholders})
            """,
            values,
        )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn


def _create_sessions_sql(*, if_not_exists: bool = False) -> str:
    column_defs = ",\n".join(
        f"{name} {definition}" for name, definition in SESSION_COLUMNS.items()
    )
    clause = "IF NOT EXISTS " if if_not_exists else ""
    return f"CREATE TABLE {clause}sessions ({column_defs})"


def _needs_table_rebuild(
    table_info: list[sqlite3.Row],
    missing_columns: set[str],
) -> bool:
    if missing_columns & _required_columns():
        return True
    info_by_name = {str(row["name"]): row for row in table_info}
    session_id_info = info_by_name.get("session_id")
    if session_id_info is None or int(session_id_info["pk"]) != 1:
        return True
    for column in _required_columns() - {"session_id"}:
        column_info = info_by_name.get(column)
        if column_info is None or int(column_info["notnull"]) != 1:
            return True
    return False


def _required_columns() -> set[str]:
    return {
        name
        for name, definition in SESSION_COLUMNS.items()
        if "PRIMARY KEY" in definition or "NOT NULL" in definition
    }


def _default_session_row(project_root: Path, now: str) -> dict[str, Any]:
    return {
        "session_id": uuid.uuid4().hex[:12],
        "native_session_id": None,
        "project_root": str(project_root),
        "cwd": str(project_root),
        "name": None,
        "status": "resumable",
        "provider": None,
        "model": None,
        "transcript_path": None,
        "handoff_path": str(project_root / DEFAULT_HANDOFF_RELATIVE),
        "parent_session_id": None,
        "started_at": now,
        "last_active_at": now,
        "last_prompt_excerpt": None,
        "last_response_excerpt": None,
        "current_task_title": None,
        "pid": None,
        "last_heartbeat_at": None,
        "terminal_start_at": None,
        "command": None,
        "metadata_json": "{}",
    }


@dataclass(frozen=True, slots=True)
class TranscriptInfo:
    path: Path
    native_session_id: str | None
    cwd: str | None
    last_prompt_excerpt: str | None
    last_response_excerpt: str | None
    generated_name: str | None


def discover_latest_transcript(
    *,
    project_root: Path,
    cwd: Path,
    started_at: str,
    native_session_id: str | None = None,
) -> TranscriptInfo | None:
    claude_projects = Path.home() / ".claude" / "projects"
    if not claude_projects.is_dir():
        return None

    started = parse_timestamp(started_at) or datetime.now(UTC)
    cutoff = started - timedelta(seconds=10)
    if native_session_id:
        exact = _discover_exact_native_transcript(claude_projects, native_session_id)
        if exact is not None:
            return exact

    candidates = [
        path
        for path in claude_projects.rglob("*.jsonl")
        if "subagents" not in {part.lower() for part in path.parts}
        and datetime.fromtimestamp(path.stat().st_mtime, UTC) >= cutoff
    ]
    unique = sorted(set(candidates), key=lambda p: p.stat().st_mtime, reverse=True)
    cwd_text = str(cwd.resolve()).lower()
    project_text = str(project_root.resolve()).lower()
    for path in unique[:25]:
        info = parse_transcript(path)
        transcript_cwd = (info.cwd or "").lower()
        if native_session_id and info.native_session_id == native_session_id:
            return info
        if transcript_cwd in {cwd_text, project_text}:
            return info
    return None


def _discover_exact_native_transcript(
    claude_projects: Path,
    native_session_id: str,
) -> TranscriptInfo | None:
    for path in claude_projects.rglob(f"{native_session_id}.jsonl"):
        if "subagents" in {part.lower() for part in path.parts}:
            continue
        info = parse_transcript(path)
        if (
            info.native_session_id == native_session_id
            or path.stem == native_session_id
        ):
            return info
    return None


def parse_transcript(path: Path) -> TranscriptInfo:
    native_session_id: str | None = path.stem
    cwd: str | None = None
    last_user: str | None = None
    last_assistant: str | None = None
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        lines = []
    for raw_line in lines:
        try:
            obj = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            session_id = obj.get("sessionId") or obj.get("session_id")
            if isinstance(session_id, str):
                native_session_id = session_id
            raw_cwd = obj.get("cwd")
            if isinstance(raw_cwd, str):
                cwd = raw_cwd
            role = _transcript_role(obj)
            text = _transcript_text(obj)
            if text:
                if role == "user":
                    last_user = _excerpt(text)
                elif role == "assistant":
                    last_assistant = _excerpt(text)
    return TranscriptInfo(
        path=path,
        native_session_id=native_session_id,
        cwd=cwd,
        last_prompt_excerpt=last_user,
        last_response_excerpt=last_assistant,
        generated_name=_slugify(last_user or path.stem),
    )


def _record_from_row(row: sqlite3.Row | dict[str, Any]) -> TerminalSessionRecord:
    return TerminalSessionRecord(
        session_id=str(row["session_id"]),
        native_session_id=row["native_session_id"],
        project_root=str(row["project_root"]),
        cwd=str(row["cwd"]),
        name=row["name"],
        status=str(row["status"]),
        provider=row["provider"],
        model=row["model"],
        transcript_path=row["transcript_path"],
        handoff_path=row["handoff_path"],
        parent_session_id=row["parent_session_id"],
        started_at=str(row["started_at"]),
        last_active_at=str(row["last_active_at"]),
        last_prompt_excerpt=row["last_prompt_excerpt"],
        last_response_excerpt=row["last_response_excerpt"],
        current_task_title=row["current_task_title"],
        pid=row["pid"],
        last_heartbeat_at=row["last_heartbeat_at"],
        terminal_start_at=row["terminal_start_at"],
        command=row["command"],
        metadata_json=row["metadata_json"],
    )


def _active_session_is_stale(record: TerminalSessionRecord) -> bool:
    if record.status != "active":
        return False
    if record.pid is not None:
        return not process_is_running(record.pid)
    last_heartbeat = parse_timestamp(record.last_heartbeat_at)
    if last_heartbeat is None:
        return True
    return (
        datetime.now(UTC) - last_heartbeat
    ).total_seconds() > ACTIVE_HEARTBEAT_STALE_SECONDS


def process_is_running(pid: int) -> bool:
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
        except FileNotFoundError, subprocess.SubprocessError, OSError:
            return False
        return str(pid) in completed.stdout
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _project_hooks_configured(project_root: Path) -> bool:
    settings_path = project_root / ".claude" / "settings.json"
    if not settings_path.is_file():
        return False
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    hooks = data.get("hooks") if isinstance(data, dict) else None
    if not isinstance(hooks, dict):
        return False
    return any(
        "scripts/hooks/session_start.py" in json.dumps(value).replace("\\", "/")
        for value in hooks.values()
    )


def _transcript_role(obj: dict[str, Any]) -> str | None:
    message = obj.get("message")
    if isinstance(message, dict) and isinstance(message.get("role"), str):
        return str(message["role"])
    if isinstance(obj.get("role"), str):
        return str(obj["role"])
    entry_type = obj.get("type")
    if entry_type in {"user", "assistant"}:
        return str(entry_type)
    return None


def _transcript_text(obj: Any) -> str:
    if isinstance(obj, str):
        return obj
    if isinstance(obj, list):
        return " ".join(_transcript_text(item) for item in obj).strip()
    if not isinstance(obj, dict):
        return ""
    block_type = obj.get("type")
    if block_type not in {None, "text", "user", "assistant", "message"}:
        return ""
    parts: list[str] = []
    for key in ("text", "content"):
        value = obj.get(key)
        if value is not None:
            text = _transcript_text(value)
            if text:
                parts.append(text)
    message = obj.get("message")
    if message is not None:
        text = _transcript_text(message)
        if text:
            parts.append(text)
    return " ".join(parts).strip()


def _excerpt(text: str, *, limit: int = 240) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 3].rstrip() + "..."


def _slugify(text: str | None) -> str | None:
    if not text:
        return None
    words = []
    for raw in text.lower().replace("_", "-").split():
        cleaned = "".join(ch for ch in raw if ch.isalnum() or ch == "-").strip("-")
        if cleaned:
            words.append(cleaned)
        if len(words) >= 5:
            break
    if not words:
        return None
    return "-".join(words)[:64]
