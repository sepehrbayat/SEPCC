"""Shared stdlib helpers for FCC Claude Code project hooks."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

MAX_CONTEXT_CHARS = 3600
MAX_ENHANCED_PROMPT_CONTEXT_CHARS = 2400
MAX_SYSTEM_MESSAGE_CHARS = 1400
MAX_VISIBLE_ENHANCED_PROMPT_CHARS = 1000
DEFAULT_PROMPT_ENHANCER_MODEL = "claude-haiku-4-5-20251001"
CONTEXT_DIR = Path(".fcc") / "context"
FACTS_FILE = CONTEXT_DIR / "facts.md"
DECISIONS_FILE = CONTEXT_DIR / "decisions.md"
HANDOFF_FILE = CONTEXT_DIR / "handoff.md"
RUNTIME_CONTRACT_FILE = CONTEXT_DIR / "agent-runtime.md"
PLUGIN_POLICY_FILE = Path(".fcc") / "plugin-policy.yml"

_DECISION_RE = re.compile(
    r"\b(decided|decision|choose|chosen|never)\b",
    re.IGNORECASE,
)


def read_hook_input() -> dict[str, Any]:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        return {}
    if isinstance(data, dict):
        return data
    return {}


def project_root(data: dict[str, Any]) -> Path:
    raw = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
    start = Path(str(raw)).expanduser().resolve()
    if start.is_file():
        start = start.parent
    return nearest_project_root(start)


def nearest_project_root(start: Path) -> Path:
    """Return the nearest parent carrying FCC/Claude project scaffolding."""
    home = Path.home().resolve()
    for candidate in (start, *start.parents):
        if candidate == home and candidate != start:
            break
        if (
            (candidate / ".fcc" / "context").is_dir()
            or (candidate / ".fcc" / "plugin-policy.yml").is_file()
            or (candidate / "scripts" / "hooks" / "_shared.py").is_file()
        ):
            return candidate
    return start


def emit_hook_json(
    event_name: str,
    *,
    additional_context: str = "",
    system_message: str = "",
) -> None:
    output: dict[str, Any] = {"suppressOutput": True}
    if additional_context:
        output["hookSpecificOutput"] = {
            "hookEventName": event_name,
            "additionalContext": additional_context[:MAX_CONTEXT_CHARS],
        }
    if system_message:
        output["systemMessage"] = system_message[:MAX_SYSTEM_MESSAGE_CHARS]
    print(json.dumps(output, ensure_ascii=True, separators=(",", ":")))


def run_hook(event_name: str, callback: Callable[[], None]) -> None:
    """Run a hook callback and always emit Claude Code hook JSON."""
    try:
        callback()
    except Exception as exc:
        msg = f"FCC {event_name} hook failed: {type(exc).__name__}"
        exc_str = str(exc)
        if exc_str and exc_str != type(exc).__name__:
            msg += f" — {exc_str}"
        emit_hook_json(
            event_name,
            system_message=msg,
        )


def read_text(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def compact_lines(text: str, *, max_lines: int = 14, max_chars: int = 1800) -> str:
    out: list[str] = []
    used = 0
    in_fence = False
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not line.strip():
            continue
        next_len = len(line) + 1
        if used + next_len > max_chars:
            break
        out.append(line)
        used += next_len
        if len(out) >= max_lines:
            break
    return "\n".join(out)


def runtime_contract(root: Path, *, max_chars: int = 1500) -> str:
    """Return the compact FCC runtime contract for injection."""
    contract = read_text(root / RUNTIME_CONTRACT_FILE)
    if not contract:
        contract = _fallback_runtime_contract()
    return compact_lines(contract, max_lines=22, max_chars=max_chars)


def _term_matches(lowered: str, terms: tuple[str, ...]) -> bool:
    """Match terms against *lowered* text.  Terms starting with ``\b``
    are treated as regex patterns; all others use substring matching."""
    for term in terms:
        if term.startswith(r"\b"):
            if re.search(term, lowered):
                return True
        elif term in lowered:
            return True
    return False


def prompt_routing_hint(prompt: str, root: Path | None = None) -> str:
    """Return a tiny routing hint for prompts that need FCC orchestration."""
    stripped = prompt.lstrip()
    if not stripped or stripped.startswith("/"):
        return ""
    if root is None:
        root = nearest_project_root(Path.cwd())
    lowered = prompt.lower()
    hints: list[str] = []
    if _term_matches(lowered, _RECALL_TERMS):
        hints.append(
            "recall: use handoff first, MemSearch for memory, Token Savior for code"
        )
    if _term_matches(lowered, _REVIEW_TERMS):
        hints.append(
            "review: use fcc-code-reviewer/product-logic subagents when useful"
        )
    if _term_matches(lowered, _RESEARCH_TERMS):
        hints.append("research: use fcc-researcher and cite primary sources")
    if _term_matches(lowered, _LARGE_WORK_TERMS):
        hints.append("large task: use bounded multi-agent review; verify before final")
    if _term_matches(lowered, _LOOP_TERMS):
        hints.append(
            "loop: Ralph Loop only if configured, bounded, and test-verifiable"
        )
    graph_hint = _graph_routing_hint(prompt, root)
    if graph_hint:
        hints.append(graph_hint)
    parts: list[str] = []
    if hints:
        parts.append("FCC routing hint: " + "; ".join(hints[:4]) + ".")
    if command_hint := command_protocol_hint(prompt):
        parts.append(command_hint)
    return " ".join(parts)


def _graph_routing_hint(prompt: str, root: Path) -> str:
    """Return a model-tier routing hint based on aggregate graph entity matching.

    Searches the knowledge graph for entities matching words in the prompt and
    computes an aggregate centrality score, cross-community count, and entity
    count. Escalates to stronger models when the prompt touches multiple
    high-impact entities — even if no single entity exceeds the threshold.
    """
    try:
        from core.graph import load_graph
        from core.graph.query import GraphQuery
    except ImportError:
        return ""
    if not isinstance(root, Path):
        return ""
    graph_json = root / ".fcc" / "graph" / "graph.json"
    if not graph_json.is_file():
        return ""
    try:
        store = load_graph(root)
        query = GraphQuery(store)
    except Exception:
        return ""

    # Extract candidate words from prompt
    words = [w.lower() for w in prompt.split() if len(w) > 2]
    if not words:
        return ""

    # Search graph for matching entities
    seen_ids: set[str] = set()
    matched: list[dict[str, Any]] = []
    for word in words[:8]:
        for r in query.search(word, top_n=3):
            if r["id"] not in seen_ids:
                seen_ids.add(r["id"])
                matched.append(r)

    # Filter: code entities with meaningful type fields
    code_matched = [
        m for m in matched
        if m.get("type") == "code"
    ]

    if not code_matched:
        return "tier:haiku (no matching code entity — exploratory task)"

    # Filter out noise: entities with centrality 0 (not connected to anything)
    significant = [m for m in code_matched
                   if (float(m.get("centrality", 0) or 0)) > 0.0]
    if significant:
        code_matched = significant

    # Aggregate metrics
    centralities = [float(m.get("centrality", 0) or 0) for m in code_matched]
    total_centrality = sum(centralities)
    max_centrality = max(centralities)
    communities = {m.get("community") for m in code_matched if m.get("community")}
    entity_count = len(code_matched)

    # Determine tier via composite score
    # sum_cent is primary; communities and entity_count are amplifiers
    composite = total_centrality + (len(communities) * 0.05) + (entity_count * 0.02)

    if (total_centrality > 1.0  # high-impact entities
            or composite > 1.2  # strong aggregate signal
            or (len(communities) > 5 and entity_count > 6 and total_centrality > 0.3)
            or (len(communities) > 7 and entity_count > 9)):  # very broad sweep
        tier = "opus"
    elif total_centrality > 0.15 or max_centrality > 0.3 or composite > 0.4:
        tier = "sonnet"
    else:
        return ""  # Default routing, no hint needed

    parts = [
        f"tier:{tier}",
        f"matched:{entity_count}",
        f"sum_cent:{total_centrality:.2f}",
        f"communities:{len(communities)}",
    ]
    return "graph(" + " ".join(parts) + ")"


def prompt_enhancement_hint(prompt: str, root: Path) -> str:
    """Return an enhanced-prompt context hint for interactive Claude Code turns."""
    additional_context, _system_message = prompt_enhancement_outputs(prompt, root)
    return additional_context


def prompt_enhancement_outputs(prompt: str, root: Path) -> tuple[str, str]:
    """Return agent context plus a visible status message for auto-enhancement."""
    if not _env_bool("AUTO_PROMPT_ENHANCER", default=True):
        return "", ""
    stripped = prompt.lstrip()
    if not stripped or stripped.startswith("/"):
        return "", ""
    api_url = _messages_api_url()
    if not api_url:
        return (
            "",
            "FCC auto-enhancer is enabled but no proxy URL is configured. "
            "Launch with fcc-claude or set ANTHROPIC_BASE_URL.",
        )

    result = _enhance_prompt_with_core(
        prompt,
        root,
        api_url=api_url,
        api_key=os.environ.get("ANTHROPIC_AUTH_TOKEN", "").strip(),
        model=_env_text("PROMPT_ENHANCER_MODEL", default=DEFAULT_PROMPT_ENHANCER_MODEL),
        timeout=_env_float("PROMPT_ENHANCER_TIMEOUT", default=12.0),
        max_output_chars=_env_int("PROMPT_ENHANCER_MAX_OUTPUT_CHARS", default=2000),
    )
    if not result.changed:
        return "", _enhancement_status_message(result)

    enhanced = result.enhanced_prompt[:MAX_ENHANCED_PROMPT_CONTEXT_CHARS]
    additional_context = (
        "FCC enhanced prompt: Treat this as clarification of the user's intent; "
        "do not mention the enhancement wrapper.\n" + enhanced
    )
    return additional_context, _enhancement_status_message(result)


def _messages_api_url() -> str:
    base = os.environ.get("ANTHROPIC_BASE_URL", "").strip()
    if not base:
        api_url = os.environ.get("ANTHROPIC_API_URL", "").strip()
        if api_url:
            api_url = api_url.rstrip("/")
            if api_url.endswith("/v1"):
                return api_url + "/messages"
            return api_url + "/v1/messages"
        port = os.environ.get("FCC_PORT", "").strip()
        if port.isdigit() and 1 <= int(port) <= 65535:
            return f"http://127.0.0.1:{port}/v1/messages"
        return ""
    base = base.rstrip("/")
    if base.endswith("/v1"):
        return base + "/messages"
    return base + "/v1/messages"


def _enhance_prompt_with_core(
    prompt: str,
    root: Path,
    *,
    api_url: str,
    api_key: str,
    model: str,
    timeout: float,
    max_output_chars: int,
) -> Any:
    package_root = os.environ.get("FCC_PACKAGE_ROOT", "").strip()
    if package_root and package_root not in sys.path:
        sys.path.insert(0, package_root)
    try:
        from core.prompt_enhancer import enhance_prompt_sync
    except Exception as exc:
        return SimpleNamespace(
            original_prompt=prompt,
            enhanced_prompt=prompt,
            status="unavailable",
            reason=type(exc).__name__,
            changed=False,
        )

    return enhance_prompt_sync(
        prompt,
        str(root),
        api_url=api_url,
        api_key=api_key,
        model=model,
        timeout=timeout,
        max_output_chars=max_output_chars,
    )


def _enhancement_status_message(result: Any) -> str:
    status = str(getattr(result, "status", ""))
    if status == "enhanced":
        enhanced = str(getattr(result, "enhanced_prompt", ""))[
            :MAX_VISIBLE_ENHANCED_PROMPT_CHARS
        ]
        return "FCC auto-enhanced prompt:\n" + enhanced
    if status == "unchanged":
        return "FCC auto-enhancer checked this prompt; no rewrite needed."
    if status in {"timeout", "error", "empty", "context_error"}:
        reason = str(getattr(result, "reason", status))
        if reason and reason != status:
            return f"FCC auto-enhancer could not refine this prompt ({status}: {reason[:120]}); using original."
        return f"FCC auto-enhancer could not refine this prompt ({status}); using original."
    if status == "unavailable":
        reason = str(getattr(result, "reason", "import_error"))
        return (
            "FCC auto-enhancer is enabled but the core enhancer is unavailable "
            f"({reason}); launch with fcc-claude."
        )
    return ""


def _env_bool(name: str, *, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"", "0", "false", "no", "off"}


def _env_float(name: str, *, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _env_text(name: str, *, default: str) -> str:
    raw = os.environ.get(name)
    if raw is None:
        return default
    value = raw.strip()
    return value or default


def _env_int(name: str, *, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _fallback_runtime_contract() -> str:
    return "\n".join(
        [
            "# FCC Agent Runtime",
            "- **MANDATORY**: .fcc/context/quality-gates.md is a binding quality contract — read and apply it before any task (pre-task gates, product-centered rules, red flags, definition of done, golden rules).",
            "- FCC is the provider/router; do not add another routing proxy.",
            "- Trust SessionStart context, then .fcc/context/handoff.md.",
            "- Durable local facts belong in CLAUDE.local.md.",
            "- Memory owner: MemSearch. Code retrieval owner: Token Savior.",
            "- Store raw logs in SQLite sidecar; do not replay transcripts.",
            "- Use subagents for large research/review/logic audits.",
            "- Ralph Loop is optional and only for bounded verified loops.",
        ]
    )


def extract_section(text: str, heading: str) -> str:
    wanted = heading.strip().lower()
    capture = False
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            current = stripped[3:].strip().lower()
            if capture:
                break
            capture = current == wanted
            continue
        if capture:
            lines.append(line)
    return "\n".join(lines).strip()


def session_name_from_prompt(prompt: str) -> str:
    """Return the first 3-4 words of a prompt as a human-readable session name."""
    words: list[str] = []
    for raw in prompt.strip().split():
        cleaned = "".join(ch for ch in raw if ch.isalnum() or ch in "-_").strip("-_")
        if cleaned:
            words.append(cleaned)
        if len(words) >= 4:
            break
    if not words:
        return ""
    return " ".join(words)


def name_active_session(root: Path, name: str) -> None:
    """Set the name of the active session in the SQLite registry, if unnamed."""
    if not name:
        return
    db = root / ".fcc" / "sessions.sqlite"
    if not db.is_file():
        return
    try:
        conn = sqlite3.connect(str(db))
        cursor = conn.execute(
            "SELECT session_id FROM sessions "
            "WHERE name IS NULL AND status = 'active' "
            "ORDER BY started_at DESC LIMIT 1"
        )
        row = cursor.fetchone()
        if row:
            conn.execute(
                "UPDATE sessions SET name = ?, current_task_title = ? "
                "WHERE session_id = ?",
                (name, name, row[0]),
            )
            conn.commit()
        conn.close()
    except Exception as exc:
        import sys
        print(
            f"FCC: could not name active session ({type(exc).__name__}: {exc})",
            file=sys.stderr,
        )


_RECALL_TERMS = (
    "recall",
    "remember",
    "forgot",
    "memory",
    "handoff",
    "context",
    "decision",
    "resume",
    "continue",
)
_REVIEW_TERMS = (
    r"\breview\b",
    "audit",
    "line by line",
    "bug",
    "risk",
    "regression",
    "logic",
)
_RESEARCH_TERMS = (
    "research",
    "docs",
    "documentation",
    "tweets",
    "twitter",
    "x.com",
    "best practice",
    "latest",
)
_LARGE_WORK_TERMS = (
    "multi-file",
    "architecture",
    "long-running",
    "end to end",
    "thorough",
    "verify",
    "tests",
)
_LOOP_TERMS = ("ralph", "loop", "iterate", "until passing", "autonomous")
_STARTUP_TERMS = (
    "init",
    "initialize",
    "onboard",
    "bootstrap",
    "project context",
    "document project",
)
_CONTEXT_COMMAND_TERMS = (
    "context full",
    "context usage",
    "too much context",
    "compact",
    "token",
    "memory bloat",
)
_REVIEW_COMMAND_TERMS = (
    "code review",
    "review diff",
    "review pr",
    "security review",
    "pull request",
)
_RUN_COMMAND_TERMS = (
    "run app",
    "verify app",
    "smoke test",
    "browser qa",
    "does it work",
)
_UI_COMMAND_TERMS = (
    "theme",
    "status line",
    "statusline",
    "terminal",
    "fullscreen",
    "shift+enter",
    "vim",
    "output style",
)
# Matches Hebrew, Arabic, Syriac, Thaana, N'Ko, and RTL presentation
# forms.  Intentionally broad: any RTL character in an otherwise-LTR
# prompt benefits from a terminal rendering hint.
_RTL_RE = re.compile(r"[\u0590-\u08ff\ufb1d-\ufdff\ufe70-\ufeff]")


def startup_command_hint(root: Path) -> str:
    """Return a startup hint when a project is missing expected Claude/FCC context."""
    hints: list[str] = []
    if not (root / "CLAUDE.md").is_file():
        hints.append(
            "start with /init to create a CLAUDE.md project guide; "
            "use fcc-bootstrap-context when FCC hooks/skills are desired"
        )
    elif not (root / RUNTIME_CONTRACT_FILE).is_file():
        hints.append(
            "run fcc-bootstrap-context to install FCC hooks, skills, and handoff files"
        )
    elif not (root / ".claude" / "settings.json").is_file():
        hints.append(
            "run fcc-bootstrap-context to install FCC hook configuration"
        )
    if not hints:
        return ""
    return "FCC command protocol: " + "; ".join(hints[:2]) + "."


def command_protocol_hint(prompt: str) -> str:
    """Return concise Claude Code built-in command guidance for the active prompt."""
    stripped = prompt.lstrip()
    if not stripped or stripped.startswith("/"):
        return ""

    lowered = prompt.lower()
    hints: list[str] = []
    if any(term in lowered for term in _STARTUP_TERMS):
        hints.append(
            "/init for CLAUDE.md project documentation; fcc-bootstrap-context for FCC scaffold"
        )
    if any(term in lowered for term in _CONTEXT_COMMAND_TERMS):
        hints.append(
            "/context all before context surgery; /compact with focus instructions when continuing"
        )
    if any(term in lowered for term in _REVIEW_COMMAND_TERMS):
        hints.append(
            "/diff to inspect changes; /code-review for correctness; /security-review for security"
        )
    if any(term in lowered for term in _RUN_COMMAND_TERMS):
        hints.append(
            "/run or /verify when a user-facing app change needs live validation"
        )
    if any(term in lowered for term in _UI_COMMAND_TERMS):
        hints.append(
            "/config, /theme, /statusline, /terminal-setup, or /tui fullscreen for CLI ergonomics"
        )
    if _RTL_RE.search(prompt) is not None:
        hints.append(
            "RTL text rendering depends on the terminal or IDE; keep code/tool output LTR"
        )
    if not hints:
        return ""
    return "FCC command protocol: " + "; ".join(hints[:3]) + "."


def parse_transcript_text(transcript_path: Path | str | None) -> str:
    if transcript_path is None:
        return ""
    path = Path(transcript_path)
    if not path.is_file():
        return ""

    entries: list[str] = []
    for raw_line in read_text(path).splitlines():
        try:
            obj = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        role = _extract_role(obj)
        if role not in {"user", "assistant"}:
            continue
        text = _extract_text(obj)
        if text:
            entries.append(f"{role}: {text}")
    return "\n".join(entries[-10:])


def summarize_transcript(text: str, *, max_items: int = 5) -> list[str]:
    if not text.strip():
        return ["- No transcript summary was available."]
    # Filter common Claude boilerplate to keep handoff actionable
    boilerplate_prefixes = (
        "assistant: i'll inspect",
        "assistant: i'll start",
        "assistant: let me",
        "assistant: first, let me",
        "assistant: now i'll",
        "assistant: i need to",
        "assistant: i can see",
        "assistant: i see",
        "assistant: let's",
    )
    meaningful = [
        line
        for line in text.splitlines()
        if not line.lower().startswith(boilerplate_prefixes)
    ]
    return bulletize(meaningful[-max_items:], max_items=max_items)


def extract_decisions(text: str, *, max_items: int = 5) -> list[str]:
    candidates = [
        line
        for line in re.split(r"[\r\n.]+", text)
        if _DECISION_RE.search(line) is not None
    ]
    return bulletize(candidates, max_items=max_items)


def bulletize(lines: list[str], *, max_items: int = 5) -> list[str]:
    bullets: list[str] = []
    seen: set[str] = set()
    for raw_line in lines:
        line = re.sub(r"\s+", " ", raw_line).strip(" -\t")
        if not line:
            continue
        if len(line) > 180:
            line = f"{line[:177].rstrip()}..."
        key = line.lower()
        if key in seen:
            continue
        seen.add(key)
        bullets.append(f"- {line}")
        if len(bullets) >= max_items:
            break
    return bullets


def regenerate_handoff(root: Path, transcript_path: Path | str | None) -> None:
    context_dir = root / CONTEXT_DIR
    context_dir.mkdir(parents=True, exist_ok=True)
    handoff_path = root / HANDOFF_FILE
    facts_path = root / FACTS_FILE
    decisions_path = root / DECISIONS_FILE

    transcript_text = parse_transcript_text(transcript_path)
    existing_handoff = read_text(handoff_path)
    facts_text = read_text(facts_path)
    decisions_text = read_text(decisions_path)
    must_lines = compact_lines(
        "\n".join(
            part
            for part in (
                extract_section(existing_handoff, "Must Not Forget"),
                facts_text,
            )
            if part.strip()
        ),
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
    content = "\n".join(
        [
            "# FCC Handoff",
            "",
            "## Must Not Forget",
            must_lines,
            "",
            "## Current State",
            current_state,
            "",
            "## Decisions",
            decisions,
            "",
            "## Next Steps",
            "- Run /verify-context before major edits.",
            "- Store raw logs in the SQLite sidecar; do not replay them into chat.",
            "",
        ]
    )
    tmp_path = handoff_path.with_suffix(".tmp")
    tmp_path.write_text(content, encoding="utf-8")
    tmp_path.replace(handoff_path)
    if decision_lines:
        append_new_decisions(decisions_path, decision_lines)


def append_new_decisions(path: Path, decisions: list[str]) -> None:
    existing = read_text(path)
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


def _extract_role(obj: dict[str, Any]) -> str | None:
    role = obj.get("role")
    if isinstance(role, str):
        return role
    message = obj.get("message")
    if isinstance(message, dict):
        nested_role = message.get("role")
        if isinstance(nested_role, str):
            return nested_role
    entry_type = obj.get("type")
    if entry_type in {"user", "assistant"}:
        return str(entry_type)
    return None


def _extract_text(obj: Any) -> str:
    if isinstance(obj, str):
        return obj
    if isinstance(obj, list):
        return " ".join(_extract_text(item) for item in obj).strip()
    if not isinstance(obj, dict):
        return ""
    block_type = obj.get("type")
    if block_type not in {None, "text", "message", "user", "assistant"}:
        return ""
    parts: list[str] = []
    for key in ("text", "content"):
        value = obj.get(key)
        if value is not None:
            text = _extract_text(value)
            if text:
                parts.append(text)
    message = obj.get("message")
    if message is not None:
        text = _extract_text(message)
        if text:
            parts.append(text)
    return " ".join(parts).strip()
