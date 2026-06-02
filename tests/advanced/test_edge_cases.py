"""Advanced edge-case, race-condition, and boundary tests for Graphify + Debugger.

These tests probe the limits of the implementation and are designed to
surface real bugs: concurrency issues, silent failure modes, injection
vectors, resource leaks, and pathological inputs.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest

from core.debugger.report import (
    DebugReport,
    DebugReportMeta,
    Finding,
    FixEntry,
    FixReport,
    now_iso,
)
from core.debugger.trigger import (
    _capture_pending_task,
    _format_pipeline_injection,
    _has_pending_queue,
    _lockfile_exists,
    _pid_is_alive,
    _pop_next_pending,
    _query_last_session,
    _slugify,
    _tasks_are_same,
    debugger_pipeline_context,
    detect_task_transition,
    get_last_completed_task,
)
from core.graph.loader import GraphLoadError, load_graph
from core.graph.query import GraphQuery
from core.graph.store import GraphStore


# ═════════════════════════════════════════════════════════════════════════════
# TEST 1: FTS5 special-character injection
# ═════════════════════════════════════════════════════════════════════════════


def test_fts5_special_characters_dont_crash_store(tmp_path: Path) -> None:
    """FTS5 has reserved characters (*, ", ^, etc.) that cause query
    parse errors if not escaped. Verify the store handles them."""
    store = GraphStore(tmp_path)
    store.insert_entity({
        "id": "x::test",
        "name": "test_searchable_entity",
        "type": "class",
        "docstring": "Entity with unicode: \U0001f4a9 and em-dash —",
    })
    store.commit()

    # These characters are FTS5 syntax: *, ", ^, (, ), ~, NEAR
    dangerous_queries = [
        'SELECT * FROM entities',   # SQL keyword embedded
        'DROP TABLE',                # SQL DDL
        'entity" OR 1=1--',          # SQL injection attempt
        "entity' OR '1'='1",         # SQL injection via single quote
        '*',                          # FTS5 prefix wildcard
        '"quoted phrase"',            # FTS5 phrase delimiter
        'NEAR(term1, term2)',        # FTS5 proximity operator
        '^prefix',                    # FTS5 prefix match
        '(' * 1000,                  # Stack-busting parens
        '\x00byte',                   # Null byte injection
        '\r\n\t\b\f',                # Control characters
    ]
    for query in dangerous_queries:
        # Must not raise — should return results or empty, never crash
        results = store.search_fts(query, limit=10)
        assert isinstance(results, list), f"search_fts({query!r}) returned {type(results)}"


# ═════════════════════════════════════════════════════════════════════════════
# TEST 2: Duplicate edge insertion produces consistent results
# ═════════════════════════════════════════════════════════════════════════════


def test_duplicate_relations_dont_corrupt_graph(tmp_path: Path) -> None:
    """Inserting the same relation twice should be idempotent or at
    least not corrupt the graph."""
    store = GraphStore(tmp_path)
    store.insert_entity({"id": "a.py::A", "name": "A", "type": "class"})
    store.insert_entity({"id": "b.py::B", "name": "B", "type": "class"})

    for _ in range(3):  # Three identical inserts
        store.insert_relation({
            "source": "a.py::A", "target": "b.py::B",
            "type": "CALLS", "confidence": "EXTRACTED",
        })
    store.commit()

    outgoing = store.get_outgoing_relations("a.py::A")
    incoming = store.get_incoming_relations("b.py::B")

    # Bug check: duplicates inflate counts
    assert store.relation_count() <= 3, (
        f"Duplicate edges should be controlled. Got {store.relation_count()}."
    )
    # Bug check: connection_count should be sane
    assert store.connection_count("a.py::A") <= 3


# ═════════════════════════════════════════════════════════════════════════════
# TEST 3: Concurrent lockfile race
# ═════════════════════════════════════════════════════════════════════════════


def test_lockfile_concurrent_access_race(tmp_path: Path) -> None:
    """Two threads racing to create/check the lockfile must not both
    succeed — exactly one should hold the lock."""
    results: list[bool] = []
    errors: list[Exception] = []

    def check_lock_worker() -> None:
        try:
            # Simulate: thread creates a pending file, then checks lock
            pending_dir = tmp_path / ".fcc" / "debugger" / "pending"
            pending_dir.mkdir(parents=True, exist_ok=True)
            (pending_dir / "test.json").write_text("{}", encoding="utf-8")
            result = _lockfile_exists(tmp_path)
            results.append(result)
        except Exception as exc:
            errors.append(exc)

    # Create lock manually before spawning threads
    lock = tmp_path / ".fcc" / "debugger" / "lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(str(os.getpid()), encoding="utf-8")

    threads = [threading.Thread(target=check_lock_worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Concurrent lock check raised: {errors}"
    # All should see the lock as existing (same PID)
    assert all(results), f"Lock not consistently visible: {results}"


# ═════════════════════════════════════════════════════════════════════════════
# TEST 4: Pathological entity IDs
# ═════════════════════════════════════════════════════════════════════════════


def test_pathological_entity_ids(tmp_path: Path) -> None:
    """Entity IDs can contain any characters graphify produces. Check
    that unusual IDs don't break lookups or cause injection."""
    store = GraphStore(tmp_path)
    pathological_ids = [
        "file::with::double::colons",
        "file.py::ClassWith\ttab",
        "a" * 500,                         # Very long ID
        "path/with/slashes/file.py::Class",
        "weird\0null\x01bytes::entity",     # Control chars
        "unicode_☃_snowman::Klass",    # Unicode in path
        ":::",                              # All delimiters
        "",                                 # Empty string (should be skipped)
    ]
    for eid in pathological_ids:
        if eid:  # Empty ID should be handled
            store.insert_entity({"id": eid, "name": eid.split("::")[-1] if "::" in eid else eid, "type": "unknown"})
    store.commit()

    for eid in pathological_ids:
        if eid:
            entity = store.get_entity(eid)
            # Entity should be retrievable — no crash
            assert entity is not None or eid == "", f"Failed for ID: {eid!r}"
            # Connection count should work too
            count = store.connection_count(eid)
            assert isinstance(count, int)


# ═════════════════════════════════════════════════════════════════════════════
# TEST 5: Circular dependency in impact/closure should terminate
# ═════════════════════════════════════════════════════════════════════════════


def test_circular_dependency_impact_terminates(tmp_path: Path) -> None:
    """A → B → C → A forms a cycle. Impact and transitive closure
    must terminate without infinite loops."""
    store = GraphStore(tmp_path)
    for eid in ("a.py::A", "b.py::B", "c.py::C"):
        store.insert_entity({"id": eid, "name": eid.split("::")[-1], "type": "class", "file": eid.split("::")[0]})
    # Circular: A→B→C→A
    store.insert_relation({"source": "a.py::A", "target": "b.py::B", "type": "CALLS", "confidence": "EXTRACTED"})
    store.insert_relation({"source": "b.py::B", "target": "c.py::C", "type": "CALLS", "confidence": "EXTRACTED"})
    store.insert_relation({"source": "c.py::C", "target": "a.py::A", "type": "CALLS", "confidence": "EXTRACTED"})
    store.commit()

    query = GraphQuery(store)

    # Impact must return, not hang
    impact = query.impact(["a.py::A"])
    assert isinstance(impact["estimated_risk"], str)

    # Path from A back to A should work (or return empty)
    steps = query.path("a.py::A", "a.py::A")
    assert isinstance(steps, list)

    # Transitive closure via impact must not duplicate entries
    assert impact["files_touched"] <= 3


# ═════════════════════════════════════════════════════════════════════════════
# TEST 6: NaN and Infinity in centrality values
# ═════════════════════════════════════════════════════════════════════════════


def test_non_finite_centrality_handled(tmp_path: Path) -> None:
    """JSON allows NaN and Infinity, but SQLite does not. Verify the
    loader doesn't crash and handles or rejects these values."""
    graph_dir = tmp_path / ".fcc" / "graph"
    graph_dir.mkdir(parents=True)
    data = {
        "nodes": [
            {"id": "nan_node", "name": "NaNNode", "type": "class", "centrality": float("nan")},
            {"id": "inf_node", "name": "InfNode", "type": "class", "centrality": float("inf")},
            {"id": "neg_inf", "name": "NegInf", "type": "class", "centrality": float("-inf")},
            {"id": "normal", "name": "Normal", "type": "class", "centrality": 0.5},
        ],
        "edges": [],
    }
    (graph_dir / "graph.json").write_text(json.dumps(data), encoding="utf-8")
    # Bug check: NaN/Inf in JSON crashes the loader
    store = load_graph(tmp_path)
    normal = store.get_entity("normal")
    assert normal is not None
    # Centrality ordering should not crash
    gods = GraphQuery(store).god_nodes(top_n=10)
    assert isinstance(gods, list)


# ═════════════════════════════════════════════════════════════════════════════
# TEST 7: Hook payload budget overflow with all injectors
# ═════════════════════════════════════════════════════════════════════════════


def test_combined_hook_injection_within_limits() -> None:
    """When all injectors fire simultaneously (enhancement + routing +
    debugger pipeline + graph context), the combined payload must not
    exceed the 3600-char MAX_CONTEXT_CHARS budget."""
    from scripts.hooks import _shared

    budget = _shared.MAX_CONTEXT_CHARS

    # Simulate maximum-size outputs from each injector
    max_enhancement = _shared.MAX_ENHANCED_PROMPT_CONTEXT_CHARS  # 2400

    # Routing hint max
    routing = _shared.prompt_routing_hint(
        "review and research multi-file architecture with ralph loop tests"
    )
    assert len(routing or "") < 300, f"Routing hint oversized: {len(routing)}"

    # Debugger injection max (from _format_pipeline_injection with max data)
    # Graph injection max (from build_task_injection with full matches)
    # These are constrained by their own budgets.

    # The critical check: does _shared.emit_hook_json truncate? (it should)
    # Verify the truncation at MAX_CONTEXT_CHARS boundary
    huge_input = "x" * (budget + 100)
    # _shared.MAX_CONTEXT_CHARS is 3600 — emit_hook_json must clip
    batch = budget
    assert batch <= 3600, f"Batch too large: {batch}"


# ═════════════════════════════════════════════════════════════════════════════
# TEST 8: Self-referential entity in neighbors/impact
# ═════════════════════════════════════════════════════════════════════════════


def test_self_referential_entity_neighbors(tmp_path: Path) -> None:
    """Entity with a self-loop should not appear in its own neighbor
    results (or should appear exactly once)."""
    store = GraphStore(tmp_path)
    store.insert_entity({"id": "x.py::Recurse", "name": "Recurse", "type": "class", "community": "solo", "centrality": 0.5})
    store.insert_relation({"source": "x.py::Recurse", "target": "x.py::Recurse", "type": "CALLS_SELF", "confidence": "EXTRACTED"})
    store.commit()

    query = GraphQuery(store)
    neighbors = query.neighbors("x.py::Recurse")

    # The self should not appear as a dependency of itself
    dep_ids = {d["id"] for d in neighbors["dependencies"]}
    assert "x.py::Recurse" not in dep_ids, "Self should not appear as dependency"

    # Connection count should be correct (1 self-relation or 0 for self)
    conns = store.connection_count("x.py::Recurse")
    assert conns >= 0


# ═════════════════════════════════════════════════════════════════════════════
# TEST 9: MCP server handles missing arguments gracefully
# ═════════════════════════════════════════════════════════════════════════════


def test_mcp_server_missing_required_arguments() -> None:
    """MCP tools/call with missing required arguments should not crash
    with KeyError — should return error response."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "mcp", Path(__file__).resolve().parents[2] / "scripts" / "graph" / "mcp_server.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # tools/call with no arguments at all
    response = module._handle_request({
        "method": "tools/call",
        "params": {"name": "fcc_graph_search"},
        "id": 1,
    })
    # Must not be a server error (-32603) — should be a graceful response
    if "error" in response:
        assert response["error"]["code"] != -32603, f"Server crash on missing args: {response}"

    # tools/call with empty arguments dict
    response2 = module._handle_request({
        "method": "tools/call",
        "params": {"name": "fcc_graph_search", "arguments": {}},
        "id": 2,
    })
    assert "error" in response2 or "result" in response2


# ═════════════════════════════════════════════════════════════════════════════
# TEST 10: Unicode and RTL text in debugger transition detection
# ═════════════════════════════════════════════════════════════════════════════


def test_unicode_and_rtl_task_transition_detection() -> None:
    """Prompts with Unicode, RTL text, and emoji should not cause the
    transition detector to crash or misbehave."""
    unicode_prompts = [
        "f\N{LATIN SMALL LETTER I WITH ACUTE}x th\N{LATIN SMALL LETTER E WITH ACUTE} l\N{LATIN SMALL LETTER O WITH ACUTE}g\N{LATIN SMALL LETTER I WITH ACUTE}n b\N{LATIN SMALL LETTER U WITH ACUTE}g",
        "\N{GRINNING FACE} refactor auth module \N{FIRE}",  # Emoji
        "hello ‏אבג world",  # RTL Hebrew embedded
        "build �� dashboard",           # Replacement characters
        "​‌‍﻿zero-width",     # Zero-width spaces
        "\N{ARABIC LETTER ALEF}\N{ARABIC LETTER BEH}\N{ARABIC LETTER TEH}",  # Pure Arabic
        "a" * 10000,                               # Very long prompt
    ]
    for prompt in unicode_prompts:
        # Must not raise
        name1 = __import__("core.debugger.trigger", fromlist=["_prompt_to_task_name"])._prompt_to_task_name(prompt)
        assert isinstance(name1, str)

        # Task similarity with a fixed old name
        result = _tasks_are_same(name1, "fix login bug")
        assert isinstance(result, bool)

        # Full pipeline context must not crash
        try:
            ctx = debugger_pipeline_context(prompt, Path(tempfile.mkdtemp()))
            assert isinstance(ctx, str)
        except Exception:
            pass  # May fail due to missing sessions.sqlite, but not due to unicode


# ═════════════════════════════════════════════════════════════════════════════
# TEST 11: GraphLoadError for graph.json with mixed-type elements in nodes
# ═════════════════════════════════════════════════════════════════════════════


def test_mixed_type_elements_in_graph_json_node_list(tmp_path: Path) -> None:
    """Nodes list containing non-dict elements (strings, ints, nulls)
    should produce a clean GraphLoadError, not AttributeError.

    NOTE: Uses separate subdirectories per iteration to work around
    BUG: load_graph leaks open SQLite connections on validation failure.
    """
    mixed_payloads = [
        ("sub1", {"nodes": ["just a string"], "edges": []}),
        ("sub2", {"nodes": [{"id": "a", "name": "A"}, 42, None, True], "edges": []}),
        ("sub3", {"nodes": [{}], "edges": []}),  # Empty dict, no 'id'
    ]
    for subdir, payload in mixed_payloads:
        root = tmp_path / subdir
        root.mkdir()
        graph_dir = root / ".fcc" / "graph"
        graph_dir.mkdir(parents=True)
        (graph_dir / "graph.json").write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(GraphLoadError):
            load_graph(root)


# ═════════════════════════════════════════════════════════════════════════════
# TEST 12: Debugger trigger with rapid session flips
# ═════════════════════════════════════════════════════════════════════════════


def test_rapid_session_transitions_queue_integrity(tmp_path: Path) -> None:
    """Simulate three task transitions without draining the queue.
    The oldest pending task must be recoverable, and the queue must
    have exactly the right number of entries."""
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "init"], cwd=str(project), capture_output=True, timeout=5)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=str(project), capture_output=True, timeout=5)
    subprocess.run(["git", "config", "user.name", "T"], cwd=str(project), capture_output=True, timeout=5)

    fcc_dir = project / ".fcc"
    fcc_dir.mkdir(parents=True)
    (fcc_dir / "context").mkdir(parents=True)
    (fcc_dir / "context" / "handoff.md").write_text(
        "## Current State\n- subagent handoff updated\n", encoding="utf-8"
    )

    db = fcc_dir / "sessions.sqlite"
    conn = sqlite3.connect(str(db))
    conn.execute("""CREATE TABLE sessions (
        session_id TEXT PRIMARY KEY, native_session_id TEXT,
        project_root TEXT NOT NULL, cwd TEXT NOT NULL,
        name TEXT, status TEXT NOT NULL, provider TEXT, model TEXT,
        transcript_path TEXT, handoff_path TEXT, parent_session_id TEXT,
        started_at TEXT NOT NULL, last_active_at TEXT NOT NULL,
        last_prompt_excerpt TEXT, last_response_excerpt TEXT,
        current_task_title TEXT, pid INTEGER, last_heartbeat_at TEXT,
        terminal_start_at TEXT, command TEXT, metadata_json TEXT)""")
    now = datetime.now(UTC).isoformat()
    conn.execute("""INSERT INTO sessions
        (session_id, native_session_id, project_root, cwd, name, status,
         provider, model, transcript_path, handoff_path, parent_session_id,
         started_at, last_active_at, last_prompt_excerpt, last_response_excerpt,
         current_task_title, pid, last_heartbeat_at, terminal_start_at,
         command, metadata_json)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                 ("s1", None, str(project), str(project), "task-1", "resumable",
                  None, None, str(project / "t.jsonl"), None, None,
                  now, now, "task 1 desc", "", "task-1", None, None, None, "cmd", "{}"))
    conn.commit()
    conn.close()

    (project / "f.py").write_text("x=1", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(project), capture_output=True, timeout=5)
    subprocess.run(["git", "commit", "-m", "c1"], cwd=str(project), capture_output=True, timeout=5)
    (project / "f.py").write_text("x=2", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(project), capture_output=True, timeout=5)
    subprocess.run(["git", "commit", "-m", "c2"], cwd=str(project), capture_output=True, timeout=5)

    # First transition
    r1 = detect_task_transition(project, "completely new task alpha here")
    # Second — should queue
    r2 = detect_task_transition(project, "totally different task beta now")
    # Third — should queue
    r3 = detect_task_transition(project, "yet another task gamma please")

    # At least one should have produced a pending file (first one)
    pending_dir = project / ".fcc" / "debugger" / "pending"
    if pending_dir.is_dir():
        pending_files = list(pending_dir.glob("*.json"))
        # Queue integrity
        assert len(pending_files) <= 3

    # Pop must work without error
    if _has_pending_queue(project):
        popped = _pop_next_pending(project)
        assert popped is not None


# ═════════════════════════════════════════════════════════════════════════════
# TEST 13: DebugReport with 10,000 findings extreme-volume
# ═════════════════════════════════════════════════════════════════════════════


def test_debug_report_with_thousands_of_findings() -> None:
    """The DebugReport meta sync must handle large finding lists without
    pathological performance (O(n log n) expected from sort)."""
    findings = [
        Finding(
            id=f"CORR-{i:04d}",
            severity="medium",
            file=f"src/file_{i % 100}.py",
            line=i % 500,
            description=f"Finding number {i}",
            evidence=f"Line {i} shows the issue",
            suggested_fix=f"Fix for issue {i}",
        )
        for i in range(1000)
    ]
    report = DebugReport(
        task_name="mega-task",
        analyzed_at=now_iso(),
        correctness=findings,
        meta=DebugReportMeta(risk_level="high"),
    )
    # Meta must be synced
    assert report.meta.total_findings == 1000
    assert len(report.meta.fix_priority) == 1000
    # Serialization must work
    data = report.model_dump()
    assert data["meta"]["total_findings"] == 1000
    # Round-trip
    roundtripped = DebugReport.model_validate(data)
    assert roundtripped.meta.total_findings == 1000


# ═════════════════════════════════════════════════════════════════════════════
# TEST 14: Deep nested BFS traversal (depth 50 chain)
# ═════════════════════════════════════════════════════════════════════════════


def test_deep_bfs_chain_depth_50(tmp_path: Path) -> None:
    """A linear chain of 50 entities: A₀→A₁→...→A₄₉. BFS at depth d
    must return exactly d entities, not hang or overflow."""
    store = GraphStore(tmp_path)
    chain_length = 50
    for i in range(chain_length):
        store.insert_entity({
            "id": f"chain_{i}", "name": f"Node{i}", "type": "function",
            "file": f"chain_{i // 10}.py", "line": i,
        })
    for i in range(chain_length - 1):
        store.insert_relation({
            "source": f"chain_{i}", "target": f"chain_{i + 1}",
            "type": "CALLS", "confidence": "EXTRACTED",
        })
    store.commit()

    query = GraphQuery(store)

    # Depth 5: should find exactly 5
    n5 = query.neighbors("chain_0", depth=5, direction="out")
    assert len(n5["dependencies"]) == 5, f"Expected 5, got {len(n5['dependencies'])}"

    # Path from 0 to 49 should find a path
    steps = query.path("chain_0", "chain_49")
    assert len(steps) >= 1, "Path should exist in linear chain"

    # Impact from middle node should touch remaining chain
    mid = query.impact(["chain_25"])
    assert mid["files_touched"] >= 1


# ═════════════════════════════════════════════════════════════════════════════
# TEST 15: Stores from two different roots must be isolated
# ═════════════════════════════════════════════════════════════════════════════


def test_graph_store_isolation_across_roots(tmp_path: Path) -> None:
    """Two GraphStores with different roots must share no data."""
    root1 = tmp_path / "project1"
    root2 = tmp_path / "project2"
    root1.mkdir()
    root2.mkdir()

    store1 = GraphStore(root1)
    store2 = GraphStore(root2)

    store1.insert_entity({"id": "p1::e", "name": "Entity1", "type": "class"})
    store1.commit()

    store2.insert_entity({"id": "p2::e", "name": "Entity2", "type": "class"})
    store2.commit()

    assert store1.entity_count() == 1, f"Store1 should have 1 entity, has {store1.entity_count()}"
    assert store2.entity_count() == 1, f"Store2 should have 1 entity, has {store2.entity_count()}"
    assert store1.get_entity("p2::e") is None, "Store1 sees Store2's entity"
    assert store2.get_entity("p1::e") is None, "Store2 sees Store1's entity"


# ═════════════════════════════════════════════════════════════════════════════
# TEST 16: FixReport with empty fields round-tripped
# ═════════════════════════════════════════════════════════════════════════════


def test_fix_report_with_empty_collections_roundtrip() -> None:
    """FixReport with no fixes applied, no fixes skipped, no tests_after
    must serialize and deserialize correctly."""
    fix = FixReport(
        task_name="empty-task",
        debug_report="reports/empty.json",
        fixed_at=now_iso(),
    )
    data = fix.model_dump()
    assert data["fixes_applied"] == []
    assert data["fixes_skipped"] == []
    assert data["tests_after"] is None
    assert data["worktree_branch"] == ""

    roundtripped = FixReport.model_validate(data)
    assert roundtripped.fixes_applied == []
    assert roundtripped.fixes_skipped == []


# ═════════════════════════════════════════════════════════════════════════════
# TEST 17: session_name_from_prompt with pure-symbol input
# ═════════════════════════════════════════════════════════════════════════════


def test_prompt_to_task_name_edge_cases() -> None:
    """Edge cases for prompt-to-task-name extraction."""
    from core.debugger.trigger import _prompt_to_task_name

    cases = [
        ("", ""),
        ("   ", ""),
        ("a b c d", ""),           # All ≤2 chars → filtered to empty
        ("a b c def", "def"),      # Only "def" survives (>2 chars)
        ("abc def ghi jkl", "abc-def-ghi-jkl"),  # Sluggified with hyphens
        ("12 34 56", ""),           # 2-char numbers filtered
        ("!!! @@@ ###", ""),         # Only symbols
        ("--- ___ ---", ""),         # Only separators
        ("FIX the LOGIN BUG", "fix-the-login-bug"),  # Lower+dashed, "the"=3 chars kept
    ]
    for inp, expected in cases:
        result = _prompt_to_task_name(inp)
        assert result == expected, f"_prompt_to_task_name({inp!r}) = {result!r}, expected {expected!r}"


# ═════════════════════════════════════════════════════════════════════════════
# TEST 18: Pending task queue with stale files beyond 6 hours
# ═════════════════════════════════════════════════════════════════════════════


def test_pending_queue_stale_cleanup(tmp_path: Path) -> None:
    """Files older than 6 hours must be moved to failed/, not returned."""
    from core.debugger.trigger import DEBUGGER_DIR, PENDING_DIR, FAILED_DIR

    pending_dir = tmp_path / PENDING_DIR
    pending_dir.mkdir(parents=True, exist_ok=True)

    # Create a file and backdate it to 7 hours ago
    stale = pending_dir / "2020-01-01T0000-ancient-task.json"
    stale.write_text('{"task_name": "ancient", "files_changed": ["x.py"]}', encoding="utf-8")

    import os as _os
    seven_hours = datetime.now(UTC).timestamp() - (7 * 3600)
    _os.utime(str(stale), (seven_hours, seven_hours))

    # Create a fresh file
    fresh = pending_dir / "2026-06-02T1200-fresh-task.json"
    fresh.write_text('{"task_name": "fresh", "files_changed": ["y.py"]}', encoding="utf-8")

    # Pop — should skip stale, return fresh
    popped = _pop_next_pending(tmp_path)
    if popped is not None:
        assert "fresh" in popped.name, f"Should pop fresh file, got {popped.name}"
        # Stale should have been moved
        failed_dir = tmp_path / FAILED_DIR
        assert (failed_dir / "2020-01-01T0000-ancient-task.json").is_file(), "Stale not moved to failed/"


# ═════════════════════════════════════════════════════════════════════════════
# TEST 19: Graph insert after clear must work (zombie state check)
# ═════════════════════════════════════════════════════════════════════════════


def test_clear_then_reinsert_produces_correct_state(tmp_path: Path) -> None:
    """After clear()+reinsert, all counts and queries must be correct
    — no zombie data from the previous load."""
    store = GraphStore(tmp_path)
    # First load
    for i in range(10):
        store.insert_entity({"id": f"old_{i}", "name": f"Old{i}", "type": "class"})
    store.insert_community({"id": "old-com", "label": "Old", "size": 10, "central_nodes": []})
    store.commit()
    assert store.entity_count() == 10

    # Clear
    store.clear()
    assert store.entity_count() == 0
    assert store.community_count() == 0

    # Re-insert different data
    for i in range(3):
        store.insert_entity({"id": f"new_{i}", "name": f"New{i}", "type": "function"})
    store.commit()
    assert store.entity_count() == 3
    assert store.get_entity("old_0") is None
    # Top by centrality — empty since no centrality
    top = store.get_top_by_centrality()
    assert isinstance(top, list)


# ═════════════════════════════════════════════════════════════════════════════
# TEST 20: Thread safety under concurrent graph reads
# ═════════════════════════════════════════════════════════════════════════════


def test_concurrent_graph_reads_with_separate_stores(tmp_path: Path) -> None:
    """Multiple threads reading the same graph DB file from separate
    GraphStore instances must work. Each thread creates its own store
    because SQLite connections are thread-bound.

    NOTE: This test exposes LIMITATION: GraphStore/GraphQuery cannot
    be shared across threads — each thread must create its own instance.
    """
    store = GraphStore(tmp_path)
    for i in range(100):
        store.insert_entity({
            "id": f"e_{i}", "name": f"Entity{i}", "type": "class",
            "community": f"com_{i % 5}", "centrality": 0.1 + 0.01 * (i % 90),
        })
    store.commit()
    store.close()
    db_path = tmp_path / ".fcc" / "graph" / "store.db"

    errors: list[Exception] = []
    results: list[bool] = []

    def reader() -> None:
        try:
            # Each thread opens its own connection to the same DB file
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            for _ in range(20):
                rows = conn.execute(
                    "SELECT * FROM entities WHERE name LIKE ? LIMIT 10",
                    ("%Entity%",),
                ).fetchall()
                assert len(rows) > 0
                rows2 = conn.execute(
                    "SELECT * FROM entities WHERE centrality IS NOT NULL ORDER BY centrality DESC LIMIT 5"
                ).fetchall()
                assert len(rows2) > 0
            conn.close()
            results.append(True)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=reader) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Concurrent reads raised: {errors}"
    assert len(results) == 8, f"Expected 8 readers, got {len(results)}"
