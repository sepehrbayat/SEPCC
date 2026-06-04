"""fcc-prompts-stats — Aggregate prompt enhancement statistics.

Reads ``.fcc/prompt_stats.jsonl`` and TRACE log events to produce a
human-readable summary of prompt enhancement performance.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def _find_project_root() -> Path | None:
    """Walk up from cwd to find .fcc directory."""
    cwd = Path.cwd()
    for parent in (cwd, *cwd.parents):
        if (parent / ".fcc").is_dir():
            return parent
    return None


def _read_stats_jsonl(path: Path) -> list[dict]:
    """Read all JSONL entries from the prompt stats file."""
    entries: list[dict] = []
    if not path.is_file():
        return entries
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if isinstance(entry, dict):
                    entries.append(entry)
            except json.JSONDecodeError:
                continue
    except OSError:
        return entries
    return entries


def _read_trace_logs(log_path: Path) -> list[dict]:
    """Scan server.log for enhancement TRACE events."""
    entries: list[dict] = []
    if not log_path.is_file():
        return entries
    try:
        for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or "enhancement" not in line:
                continue
            try:
                data = json.loads(line)
                if isinstance(data, dict) and data.get("stage") == "enhancement":
                    entries.append(data)
            except json.JSONDecodeError:
                continue
    except OSError:
        pass
    return entries


def _status_icon(status: str) -> str:
    icons = {
        "enhanced": "[OK]",
        "unchanged": "[=]",
        "skipped": "[~]",
        "timeout": "[T]",
        "error": "[X]",
        "empty": "[0]",
        "context_error": "[?]",
    }
    return icons.get(status, "[?]")


def main() -> None:
    """Print prompt enhancement statistics."""
    root = _find_project_root()
    if root is None:
        print("No `.fcc` directory found. Run from a SEPCC project root.")
        return

    print(f"Project: {root}\n")

    # === Section 1: JSONL stats file ===
    stats_path = root / ".fcc" / "prompt_stats.jsonl"
    jsonl_entries = _read_stats_jsonl(stats_path)

    if jsonl_entries:
        print("=== Prompt Enhancement Stats (.fcc/prompt_stats.jsonl) ===")
        total = len(jsonl_entries)
        status_counts = Counter(e.get("status", "unknown") for e in jsonl_entries)
        changed_count = sum(1 for e in jsonl_entries if e.get("changed"))

        print(f"  Total attempts: {total}")
        print(f"  Changed prompts: {changed_count} ({changed_count/max(total,1)*100:.1f}%)")
        print(f"\n  Status breakdown:")
        for status, count in status_counts.most_common():
            icon = _status_icon(status)
            pct = count / max(total, 1) * 100
            print(f"    {icon} {status}: {count} ({pct:.1f}%)")

        # Char deltas
        orig_chars = [e.get("original_chars", 0) for e in jsonl_entries]
        enh_chars = [e.get("enhanced_chars", 0) for e in jsonl_entries if e.get("changed")]
        if orig_chars:
            print(f"\n  Avg original chars: {sum(orig_chars)/len(orig_chars):.0f}")
        if enh_chars:
            print(f"  Avg enhanced chars: {sum(enh_chars)/len(enh_chars):.0f}")

        # Time range
        timestamps = [e["timestamp"] for e in jsonl_entries if e.get("timestamp")]
        if timestamps:
            print(f"  First: {timestamps[0]}")
            print(f"  Last:  {timestamps[-1]}")
    else:
        print("=== Prompt Enhancement Stats ===")
        print("  No entries in .fcc/prompt_stats.jsonl yet.")
        print("  Stats are recorded when prompt enhancement runs.")
        print("  After using the proxy, run this command again.\n")

    # === Section 2: TRACE logs (if available) ===
    log_paths = [
        Path.home() / ".fcc" / "logs" / "server.log",
        root / "logs" / "server.log",
    ]
    trace_entries: list[dict] = []
    for lp in log_paths:
        if lp.is_file():
            trace_entries = _read_trace_logs(lp)
            if trace_entries:
                break

    if trace_entries:
        print("\n=== TRACE Log Events (from server.log) ===")
        event_counts = Counter(e.get("event", "unknown") for e in trace_entries)
        for event, count in event_counts.most_common():
            print(f"  {event}: {count}")
        print(f"\n  Total TRACE events: {len(trace_entries)}")
    else:
        print("\n=== TRACE Log Events ===")
        print("  No enhancement trace events found in server.log.")
        print("  (Trace events require loguru configuration in the caller process.)\n")

    # === Section 3: Quick verdict ===
    print("\n=== Verdict ===")
    if jsonl_entries:
        enhanced_pct = status_counts.get("enhanced", 0) / max(total := len(jsonl_entries), 1) * 100
        if enhanced_pct > 70:
            print(f"  > Enhancer is effective: {enhanced_pct:.0f}% of prompts enhanced")
        elif enhanced_pct > 30:
            print(f"  ! Enhancer sometimes effective: {enhanced_pct:.0f}% enhanced")
        else:
            print(f"  X Enhancer rarely effective: {enhanced_pct:.0f}% enhanced")
        if status_counts.get("timeout", 0) > total * 0.1:
            print("  ! High timeout rate - consider increasing enhancer timeout")
        if status_counts.get("error", 0) > total * 0.1:
            print("  ! High error rate - check enhancer LLM availability")
    else:
        print("  No data yet. Run the proxy to collect stats.")


if __name__ == "__main__":
    main()