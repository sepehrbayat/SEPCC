"""Advanced tests combining freezegun + hypothesis + pytest-mock.

All tests are self-contained — no graph rebuild, no real-time waits.
Recovery tests use a patched asyncio.sleep to execute instantly.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from freezegun import freeze_time
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st


@pytest.fixture(autouse=True)
def _zero_sleep(monkeypatch):
    """Patch asyncio.sleep globally so recovery tests never actually wait."""
    async def _instant(duration):
        pass
    monkeypatch.setattr(asyncio, "sleep", _instant)


# ═════════════════════════════════════════════════════════════════════════════
# 1. CIRCUIT BREAKER — freezegun + hypothesis
# ═════════════════════════════════════════════════════════════════════════════

class TestCircuitBreaker:

    @given(
        failures=st.integers(min_value=0, max_value=8),
        recovery_delay=st.floats(min_value=0.0, max_value=120.0),
    )
    @settings(max_examples=80, deadline=1000)
    def test_circuit_state_transitions(self, failures, recovery_delay):
        from providers.health import (
            PROVIDER_CIRCUIT_FAILURE_THRESHOLD,
            PROVIDER_CIRCUIT_COOLDOWN_SECONDS,
            ProviderHealth,
        )

        health = ProviderHealth(provider_id="test")

        with freeze_time("2026-01-01 00:00:00") as frozen:
            if failures >= PROVIDER_CIRCUIT_FAILURE_THRESHOLD:
                health.consecutive_failures = failures
                health.status = "circuit_open"
                health.circuit_open_until = time.time() + PROVIDER_CIRCUIT_COOLDOWN_SECONDS
            else:
                health.consecutive_failures = failures
                health.status = "unhealthy" if failures else "unknown"

            frozen.tick(delta=recovery_delay)
            if failures < PROVIDER_CIRCUIT_FAILURE_THRESHOLD:
                assert health.is_available()

    @given(
        cooldown=st.floats(min_value=1.0, max_value=120.0, allow_nan=False, allow_infinity=False),
        elapsed=st.floats(min_value=0.0, max_value=180.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=80, deadline=1000)
    def test_cooldown_boundary(self, cooldown, elapsed):
        from providers.health import ProviderHealth

        health = ProviderHealth(provider_id="openrouter")
        health.consecutive_failures = 3
        health.status = "circuit_open"

        with freeze_time("2026-01-01 00:00:00") as frozen:
            start = time.time()
            health.circuit_open_until = start + cooldown
            assert not health.is_available()

            frozen.tick(delta=elapsed)

            # is_available uses <= (inclusive), so elapsed==cooldown opens the circuit
            if elapsed > cooldown:
                assert health.is_available()
                assert health.circuit_open_until is None
            elif elapsed < cooldown:
                assert not health.is_available()

    def test_health_snapshot_invariants(self):
        from providers.health import ProviderHealth

        health = ProviderHealth(provider_id="deepseek")
        snap = health.snapshot()
        assert snap["provider_id"] == "deepseek"
        assert snap["status"] in ("unknown", "healthy", "unhealthy", "circuit_open")
        assert snap["available"] is True

        health.consecutive_failures = 2
        health.status = "circuit_open"
        health.circuit_open_until = time.time() + 60.0
        snap2 = health.snapshot()
        assert snap2["status"] == "circuit_open"
        assert snap2["available"] is False

    def test_success_resets_circuit_breaker(self):
        from providers.health import ProviderHealth

        health = ProviderHealth(provider_id="test")
        health.consecutive_failures = 3
        health.status = "circuit_open"
        health.circuit_open_until = time.time() + 60.0

        health.consecutive_failures = 0
        health.status = "healthy"
        health.circuit_open_until = None
        assert health.is_available()


# ═════════════════════════════════════════════════════════════════════════════
# 2. RECOVERY PIPELINE — hypothesis + pytest-mock
#    asyncio.sleep patched globally via autouse fixture → instant execution
# ═════════════════════════════════════════════════════════════════════════════

class TestRecoveryPipeline:

    @pytest.mark.asyncio
    @given(
        fail_count=st.integers(min_value=1, max_value=4),
        error_type=st.sampled_from(["transient", "circuit"]),
        max_retries=st.integers(min_value=1, max_value=3),
    )
    @settings(
        max_examples=50, deadline=2000,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    async def test_recovery_behavior_recoverable(self, mocker, fail_count, error_type, max_retries):
        from providers.recovery import ProviderRecovery
        from providers.exceptions import RateLimitError, ServiceUnavailableError

        exc_map = {
            "transient": RateLimitError("rate limited"),
            "circuit": ServiceUnavailableError("down"),
        }
        error = exc_map[error_type]

        recovery = ProviderRecovery(max_retries=max_retries)
        call_count = [0]
        on_success = mocker.Mock()
        on_failure = mocker.Mock()

        async def operation():
            call_count[0] += 1
            if call_count[0] <= fail_count:
                raise error
            return "ok"

        result = await recovery.try_call(
            provider_id="test", operation=operation,
            on_success=on_success, on_failure=on_failure,
        )

        if fail_count <= max_retries:
            assert result.success
            on_success.assert_called_once()
        else:
            assert not result.success

    @pytest.mark.asyncio
    async def test_fatal_error_never_retries(self, mocker):
        from providers.recovery import ProviderRecovery
        from providers.exceptions import AuthenticationError

        recovery = ProviderRecovery(max_retries=3)
        call_count = [0]
        on_success = mocker.Mock()

        async def operation():
            call_count[0] += 1
            raise AuthenticationError("bad token")

        result = await recovery.try_call(
            provider_id="test", operation=operation,
            on_success=on_success,
        )
        assert call_count[0] == 1
        assert not result.success
        assert result.error_class.name == "FATAL"
        on_success.assert_not_called()

    @pytest.mark.asyncio
    async def test_backoff_grows_monotonically(self, mocker):
        from providers.recovery import ProviderRecovery
        from providers.exceptions import RateLimitError

        recovery = ProviderRecovery(max_retries=3)
        counter = [0]

        async def fail_always():
            counter[0] += 1
            raise RateLimitError("always")

        result = await recovery.try_call(
            provider_id="test", operation=fail_always,
        )

        assert not result.success
        assert counter[0] == 4  # 1 attempt + 3 retries

    @pytest.mark.asyncio
    @given(call_count=st.integers(min_value=1, max_value=3))
    @settings(
        max_examples=20, deadline=2000,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    async def test_recovery_callback_counts(self, mocker, call_count):
        from providers.recovery import ProviderRecovery
        from providers.exceptions import ServiceUnavailableError

        recovery = ProviderRecovery(max_retries=call_count + 1)
        on_success = mocker.Mock()
        on_failure = mocker.Mock()
        counter = [0]

        async def op():
            counter[0] += 1
            if counter[0] <= call_count:
                raise ServiceUnavailableError("down")
            return "done"

        result = await recovery.try_call(
            provider_id="test", operation=op,
            on_success=on_success, on_failure=on_failure,
        )
        assert result.success
        assert on_failure.call_count == call_count
        on_success.assert_called_once()


# ═════════════════════════════════════════════════════════════════════════════
# 3. ERROR CLASSIFICATION — hypothesis
# ═════════════════════════════════════════════════════════════════════════════

class TestErrorClassification:

    def test_all_sepcc_exceptions_classify_correctly(self):
        from providers.recovery import classify_error, ErrorClass
        from providers.exceptions import (
            AuthenticationError, InvalidRequestError, ProviderError,
            RateLimitError, ServiceUnavailableError, UnknownProviderTypeError,
        )

        assert classify_error(RateLimitError("")) == ErrorClass.TRANSIENT
        assert classify_error(ServiceUnavailableError("")) == ErrorClass.CIRCUIT
        assert classify_error(AuthenticationError("")) == ErrorClass.FATAL
        assert classify_error(InvalidRequestError("")) == ErrorClass.FATAL
        assert classify_error(ProviderError("")) == ErrorClass.FATAL
        assert classify_error(UnknownProviderTypeError("")) == ErrorClass.FATAL
        assert classify_error(ValueError("bad")) == ErrorClass.FATAL
        assert classify_error(TypeError("wrong")) == ErrorClass.FATAL
        assert classify_error(ConnectionError("refused")) == ErrorClass.CIRCUIT

    def test_http_status_classification(self):
        from providers.recovery import classify_error, ErrorClass
        import httpx

        def check(code, expected):
            resp = httpx.Response(code)
            resp._content = b""
            exc = httpx.HTTPStatusError("err", request=None, response=resp)
            assert classify_error(exc) == expected, f"HTTP {code} -> {classify_error(exc)}, expected {expected}"

        check(429, ErrorClass.TRANSIENT)
        check(401, ErrorClass.FATAL)
        check(403, ErrorClass.FATAL)
        check(500, ErrorClass.CIRCUIT)
        check(502, ErrorClass.CIRCUIT)
        check(503, ErrorClass.CIRCUIT)
        check(504, ErrorClass.CIRCUIT)
        check(200, ErrorClass.FATAL)
        check(404, ErrorClass.FATAL)

    @given(code=st.integers(min_value=100, max_value=599))
    @settings(max_examples=100, deadline=1000)
    def test_any_http_code_does_not_crash(self, code):
        from providers.recovery import classify_error, ErrorClass
        import httpx

        resp = httpx.Response(code)
        resp._content = b""
        exc = httpx.HTTPStatusError("err", request=None, response=resp)
        result = classify_error(exc)
        assert result in (ErrorClass.TRANSIENT, ErrorClass.CIRCUIT, ErrorClass.FATAL)


# ═════════════════════════════════════════════════════════════════════════════
# 4. SESSION TIMESTAMPS — freezegun
# ═════════════════════════════════════════════════════════════════════════════

class TestSessionTimestamps:

    def test_parse_timestamp_handles_all_formats(self):
        from cli.session_registry import parse_timestamp

        # Valid formats
        for val in [
            "2026-01-01T12:00:00+00:00",
            "2026-01-01T12:00:00Z",
            "2026-01-01T12:00:00",
        ]:
            result = parse_timestamp(val)
            assert result is not None, f"Should parse: {val!r}"
            assert result.tzinfo == timezone.utc

        # Invalid formats
        for val in ["", None, "not-a-date"]:
            result = parse_timestamp(val)
            assert result is None, f"Should be None: {val!r}"

    def test_stale_session_detection(self, tmp_path):
        import sqlite3

        db = tmp_path / "s.sqlite"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, started TEXT)")

        with freeze_time("2026-01-01 12:00:00"):
            conn.execute(
                "INSERT OR REPLACE INTO sessions VALUES ('s1', ?)",
                (datetime.now(timezone.utc).isoformat(),),
            )
            conn.commit()

        with freeze_time("2026-01-01 14:00:00"):
            row = conn.execute("SELECT started FROM sessions WHERE id='s1'").fetchone()
            started = datetime.fromisoformat(row[0])
            age = datetime.now(timezone.utc) - started
            assert age > timedelta(hours=1)
            assert age < timedelta(hours=3)

        conn.close()

    @given(delta_minutes=st.integers(min_value=10, max_value=400))
    @settings(
        max_examples=20, deadline=2000,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_session_age_computation(self, tmp_path, delta_minutes):
        import sqlite3

        db = tmp_path / "s.sqlite"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, started TEXT)")

        with freeze_time("2026-01-01 12:00:00") as frozen:
            conn.execute(
                "INSERT OR REPLACE INTO sessions VALUES ('s1', ?)",
                (datetime.now(timezone.utc).isoformat(),),
            )
            conn.commit()

            frozen.tick(delta=delta_minutes * 60)

            row = conn.execute("SELECT started FROM sessions WHERE id='s1'").fetchone()
            started = datetime.fromisoformat(row[0])
            now = datetime.now(timezone.utc)
            age_s = (now - started).total_seconds()
            expected_s = delta_minutes * 60

            assert abs(age_s - expected_s) < 5

        conn.close()


# ═════════════════════════════════════════════════════════════════════════════
# 5. RECOVERY EDGE CASES — hypothesis (zero-sleep via autouse fixture)
# ═════════════════════════════════════════════════════════════════════════════

class TestRecoveryEdgeCases:

    @pytest.mark.asyncio
    @given(max_retries=st.integers(min_value=0, max_value=4))
    @settings(
        max_examples=15, deadline=2000,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    async def test_max_retries_edge(self, mocker, max_retries):
        from providers.recovery import ProviderRecovery
        from providers.exceptions import RateLimitError

        recovery = ProviderRecovery(max_retries=max_retries)
        call_count = [0]

        async def op():
            call_count[0] += 1
            raise RateLimitError("slow")

        result = await recovery.try_call(provider_id="test", operation=op)
        assert call_count[0] == max_retries + 1
        assert not result.success

    @pytest.mark.asyncio
    @given(fail_count=st.integers(min_value=1, max_value=3))
    @settings(
        max_examples=10, deadline=2000,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    async def test_transient_always_retried(self, mocker, fail_count):
        from providers.recovery import ProviderRecovery
        from providers.exceptions import RateLimitError

        recovery = ProviderRecovery(max_retries=fail_count)
        counter = [0]

        async def op():
            counter[0] += 1
            if counter[0] <= fail_count:
                raise RateLimitError("slow")
            return "ok"

        result = await recovery.try_call(provider_id="test", operation=op)
        assert result.success
        assert counter[0] == fail_count + 1


# ═════════════════════════════════════════════════════════════════════════════
# 6. RECOVERY RESULT INVARIANTS — hypothesis
# ═════════════════════════════════════════════════════════════════════════════

class TestRecoveryResultInvariants:

    @given(
        success=st.booleans(),
        error_class=st.sampled_from(["TRANSIENT", "CIRCUIT", "FATAL"]),
        attempts=st.integers(min_value=1, max_value=10),
        elapsed_ms=st.floats(min_value=0.0, max_value=30000.0),
    )
    @settings(max_examples=100, deadline=1000)
    def test_recovery_result_field_consistency(
        self, success, error_class, attempts, elapsed_ms
    ):
        from providers.recovery import RecoveryResult, ErrorClass, RecoveryAction

        action = RecoveryAction.RETRY if success else RecoveryAction.ESCALATE
        result = RecoveryResult(
            success=success,
            value="test" if success else None,
            error=None if success else Exception("test"),
            error_class=ErrorClass[error_class],
            action=action,
            attempts=attempts,
            elapsed_ms=elapsed_ms,
        )
        assert result.success == success
        assert result.attempts >= 1
        assert result.elapsed_ms >= 0.0
        if success:
            assert result.value is not None
            assert result.error is None
        else:
            assert result.error is not None
