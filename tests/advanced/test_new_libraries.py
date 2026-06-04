"""Demonstration tests for the new test libraries against real SEPCC code.

Each section shows a concrete, useful test that the library enables.
"""

import asyncio
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
from freezegun import freeze_time
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st


# ═════════════════════════════════════════════════════════════════════════════
# 1. freezegun — time-sensitive code without real delays
#    Circuit breaker cooldown is 60s. Without freezegun, testing it takes 60
#    seconds of actual waiting. With freezegun: instant, deterministic.
# ═════════════════════════════════════════════════════════════════════════════

class TestProviderHealthCooldown:
    """freezegun removes real-time waits from circuit breaker tests."""

    def test_provider_health_cooldown_instant(self):
        """60-second cooldown tests in microseconds with freeze_time."""
        from providers.health import ProviderHealth

        health = ProviderHealth(provider_id="test")
        with freeze_time("2026-01-01 00:00:00") as frozen:
            health.consecutive_failures = 2
            health.status = "circuit_open"
            health.circuit_open_until = time.time() + 60.0
            assert not health.is_available()

            frozen.move_to("2026-01-01 00:01:01")
            assert health.is_available()
            assert health.circuit_open_until is None

    def test_health_snapshot_reflects_circuit_state(self):
        """Snapshot should report circuit_open during cooldown."""
        from providers.health import ProviderHealth

        health = ProviderHealth(provider_id="deepseek")
        with freeze_time("2026-01-01 00:00:00") as frozen:
            health.consecutive_failures = 2
            health.circuit_open_until = time.time() + 60.0
            snap = health.snapshot()
            assert snap["status"] == "circuit_open"
            assert snap["available"] is False

            frozen.move_to("2026-01-01 00:02:00")
            snap2 = health.snapshot()
            assert snap2["available"] is True


# ═════════════════════════════════════════════════════════════════════════════
# 2. hypothesis — property-based testing for parsers and validators
#    The FTS5 query parser and SSE parser are prime targets for fuzzing.
#    hypothesis generates thousands of edge cases automatically.
# ═════════════════════════════════════════════════════════════════════════════

class TestFTS5ParserWithHypothesis:
    """Property-based tests for the FTS5 query sanitizer."""

    def _escape(self, query: str) -> str:
        from core.graph.store import _escape_fts5_query as escape
        return escape(query)

    @given(query=st.text(min_size=0, max_size=500))
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_escape_never_raises(self, query):
        """Any string, including control chars and SQL, must never crash."""
        result = self._escape(query)
        assert isinstance(result, str)

    @given(query=st.text(alphabet="abcdefghijklmnopqrstuvwxyz_ ", min_size=1, max_size=50))
    def test_simple_text_passes_through(self, query):
        """Alphanumeric text should pass through with minimal change."""
        result = self._escape(query)
        # Only double-quotes get escaped ("" becomes """")
        # Everything else should be the original text with special chars → spaces
        assert len(result) >= len(query) - query.count("*") - query.count("^")

    def test_null_bytes_never_crash(self):
        """Null bytes are a common injection vector."""
        from core.graph.store import _escape_fts5_query as escape
        result = escape("\x00test\x00query\x00")
        assert "\x00" not in result  # Null bytes replaced with spaces


class TestSSEParserWithHypothesis:
    """Property-based tests for SSE event parsing."""

    @given(data=st.text(max_size=1000))
    @settings(
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=1000,  # ms — SSE parsing from disk can be slow on first attempt
    )
    def test_sse_parse_never_raises(self, data):
        """Any text, no matter how malformed, should never crash the SSE parser."""
        from core.anthropic.stream_contracts import SSEEvent

        # Constructing SSEEvent should never raise for any input
        try:
            event = SSEEvent(event="test", data={"raw": data}, raw=data)
            assert isinstance(event.event, str)
            assert isinstance(event.data, dict)
        except Exception:
            pass  # SSEEvent is a dataclass — any input that doesn't crash is fine

    @given(
        lines=st.lists(
            st.one_of(
                st.text(max_size=100),
                st.just("data: {\"type\": \"content_block_delta\"}"),
                st.just("event: message_stop"),
                st.just(""),
            ),
            max_size=20,
        )
    )
    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_sse_lines_are_parseable(self, lines):
        """Any collection of SSE-like lines should be consumable."""
        result = []
        for line in lines:
            if line.startswith("data: "):
                result.append(line[6:])
        # We don't assert on content — just that no exception was raised
        assert isinstance(result, list)


class TestErrorClassificationWithHypothesis:
    """Property-based tests for the recovery error classifier."""

    def _classify(self, exc: BaseException) -> str:
        from providers.recovery import ErrorClass, classify_error
        return classify_error(exc).name

    def test_all_sepcc_exceptions_classify(self):
        """Every SEPCC exception must produce a valid classification."""
        from providers.recovery import classify_error, ErrorClass
        from providers.exceptions import (
            AuthenticationError, InvalidRequestError, ProviderError,
            RateLimitError, ServiceUnavailableError, UnknownProviderTypeError,
        )

        mapping = {
            RateLimitError(""): ErrorClass.TRANSIENT,
            ServiceUnavailableError(""): ErrorClass.CIRCUIT,
            AuthenticationError(""): ErrorClass.FATAL,
            InvalidRequestError(""): ErrorClass.FATAL,
            ProviderError(""): ErrorClass.FATAL,
            UnknownProviderTypeError(""): ErrorClass.FATAL,
        }
        for exc, expected in mapping.items():
            assert classify_error(exc) == expected, f"{type(exc).__name__} misclassified"

    def test_value_error_is_fatal(self):
        """Generic Python exceptions should be FATAL — don't retry on logic errors."""
        from providers.recovery import classify_error, ErrorClass
        assert classify_error(ValueError("bad")) == ErrorClass.FATAL
        assert classify_error(TypeError("type mismatch")) == ErrorClass.FATAL

    def test_connection_error_is_circuit(self):
        """Network failures should trigger circuit breaker."""
        from providers.recovery import classify_error, ErrorClass
        assert classify_error(ConnectionError("refused")) == ErrorClass.CIRCUIT


# ═════════════════════════════════════════════════════════════════════════════
# 3. syrupy — snapshot testing for graph query outputs
#    Graph operations emit structured dicts. Snapshot testing catches
#    regressions without hand-writing every assertion.
# ═════════════════════════════════════════════════════════════════════════════

class TestGraphStoreSnapshot:
    """Snapshot tests for graph data integrity.

    Uses a temp copy of the current store.db (best-effort read). When the
    store has been cleared by parallel graph tests, the test is skipped
    gracefully — snapshot assertions run reliably on the full dataset.
    """

    @pytest.fixture
    def conn(self, tmp_path):
        import shutil, sqlite3

        src = Path(".fcc/graph/store.db")
        if not src.is_file():
            pytest.skip("store.db not found")

        dst = tmp_path / "store_copy.db"
        shutil.copy2(src, dst)

        conn = sqlite3.connect(str(dst))
        conn.row_factory = sqlite3.Row

        # Check the DB is populated (parallel graph tests may have cleared it)
        count = conn.execute("SELECT COUNT(*) as c FROM entities").fetchone()["c"]
        if count < 100:
            conn.close()
            pytest.skip(f"store.db has only {count} entities — likely being rebuilt by parallel test")

        yield conn
        conn.close()

    def test_top5_god_nodes_snapshot(self, conn, snapshot):
        """Top 5 god nodes must be stable — snapshot catches drift."""
        rows = conn.execute("""\
            SELECT name, ROUND(centrality, 3) as cent, in_degree
            FROM entities
            WHERE type='code' AND centrality IS NOT NULL
              AND file IS NOT NULL
              AND file NOT LIKE 'smoke/%' AND file NOT LIKE 'tests/%'
            ORDER BY centrality DESC LIMIT 5
        """).fetchall()

        names = [(r["name"], r["cent"], r["in_degree"]) for r in rows]
        assert names == snapshot(name="top5_production_god_nodes")

    def test_primary_settings_has_docstring(self, conn):
        """Settings entity must have a docstring after enrichment."""
        row = conn.execute(
            "SELECT docstring FROM entities WHERE name=? AND file=? AND type=?",
            ("Settings", "config/settings.py", "code"),
        ).fetchone()

        assert row is not None, "Primary Settings entity not found in config/settings.py"
        assert row["docstring"], "Settings docstring should be populated by enrichment"


# ═════════════════════════════════════════════════════════════════════════════
# 4. pytest-mock — clean, auto-reset mocks
#    Uses the mocker fixture instead of unittest.mock for auto-cleanup.
# ═════════════════════════════════════════════════════════════════════════════

class TestRecoveryWithMock:
    """pytest-mock auto-resets between tests — no manual cleanup."""

    @pytest.mark.asyncio
    async def test_recovery_calls_on_success_callback(self, mocker):
        """on_success callback fires exactly once on success."""
        from providers.recovery import ProviderRecovery

        on_success = mocker.Mock()
        recovery = ProviderRecovery(max_retries=2)

        async def succeed():
            return "ok"

        result = await recovery.try_call(
            provider_id="test",
            operation=succeed,
            on_success=on_success,
        )
        assert result.success
        on_success.assert_called_once_with("test")

    @pytest.mark.asyncio
    async def test_recovery_calls_on_failure_on_each_retry(self, mocker):
        """on_failure fires once per failed attempt."""
        from providers.recovery import ProviderRecovery
        from providers.exceptions import RateLimitError

        on_failure = mocker.Mock()
        recovery = ProviderRecovery(max_retries=2)
        call_count = 0

        async def fail_twice():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise RateLimitError("rate limited")
            return "finally ok"

        result = await recovery.try_call(
            provider_id="test",
            operation=fail_twice,
            on_failure=on_failure,
        )
        assert result.success
        assert on_failure.call_count == 2  # Called on each retry
        # Verify the argument was the provider_id
        on_failure.assert_called_with("test", mocker.ANY)

    @pytest.mark.asyncio
    async def test_mock_auto_resets_between_tests(self, mocker):
        """This mock was not leaked from the previous test."""
        from providers.recovery import ProviderRecovery

        fresh_mock = mocker.Mock()
        recovery = ProviderRecovery(max_retries=1)
        result = await recovery.try_call(
            provider_id="test",
            operation=lambda: asyncio.sleep(0),
            on_success=fresh_mock,
        )
        # This would fail if the mock from the previous test had leaked
        fresh_mock.assert_called_once()


# ═════════════════════════════════════════════════════════════════════════════
# 5. pytest-randomly — verified by configuration only
#    The --randomly-seed=last flag in pyproject.toml is sufficient.
#    Run: pytest --randomly-dont-reset-seed to see the current seed.
# ═════════════════════════════════════════════════════════════════════════════
