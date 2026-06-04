"""Structured recovery strategies for provider operations.

Wraps the circuit breaker, rate limiter, and retry heuristics into a single
recovery interface.  Each strategy classifies errors, decides whether to
retry or escalate, and logs recovery actions for observability.

This fills the gap between ``providers/exceptions.py`` (error definitions)
and individual provider clients (ad-hoc retry logic).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

import httpx
from loguru import logger

from providers.exceptions import (
    ProviderError,
    RateLimitError,
    ServiceUnavailableError,
)


class ErrorClass(Enum):
    """Classification of a provider error for recovery decisions."""

    TRANSIENT = auto()   # Retryable: rate limits, temporary unavailability
    CIRCUIT = auto()     # Retryable but decrements circuit breaker
    FATAL = auto()       # Not retryable: auth failures, invalid requests


class RecoveryAction(Enum):
    """Action taken by the recovery layer after an error."""

    RETRY = auto()
    SKIP = auto()
    ESCALATE = auto()


@dataclass
class RecoveryResult:
    """Outcome of a provider operation through the recovery layer."""

    success: bool
    value: Any | None = None
    error: BaseException | None = None
    error_class: ErrorClass = ErrorClass.FATAL
    action: RecoveryAction = RecoveryAction.ESCALATE
    attempts: int = 1
    elapsed_ms: float = 0.0
    detail: str = ""


@dataclass
class RecoveryDecision:
    """Decision metadata — logged before action is taken."""

    provider_id: str
    error_type: str
    error_class: ErrorClass
    action: RecoveryAction
    attempt: int
    max_retries: int
    backoff_seconds: float
    reason: str = ""


# ── Error classification ──────────────────────────────────────────────────

_RETRYABLE_HTTP = frozenset({429, 500, 502, 503, 504})


def classify_error(exc: BaseException) -> ErrorClass:
    """Classify a caught exception for recovery decision-making.

    - TRANSIENT: rate limits, temporary upstream issues → can retry immediately
    - CIRCUIT: service unavailable, connection failures → retry with backoff
    - FATAL: auth errors, validation errors, client mistakes → escalate to caller
    """
    if isinstance(exc, RateLimitError):
        return ErrorClass.TRANSIENT
    if isinstance(exc, ServiceUnavailableError):
        return ErrorClass.CIRCUIT
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status == 429:
            return ErrorClass.TRANSIENT
        if status in _RETRYABLE_HTTP:
            return ErrorClass.CIRCUIT
        if status in (401, 403):
            return ErrorClass.FATAL
        return ErrorClass.FATAL
    if isinstance(exc, httpx.ConnectError | httpx.TimeoutException | ConnectionError):
        return ErrorClass.CIRCUIT
    return ErrorClass.FATAL


def is_recoverable(exc: BaseException) -> bool:
    """Return True when the error might succeed on retry."""
    return classify_error(exc) != ErrorClass.FATAL


# ── Recovery strategy ─────────────────────────────────────────────────────


def _backoff(attempt: int, base: float = 0.5, max_wait: float = 30.0) -> float:
    """Exponential backoff with jitter."""
    import random
    wait = min(base * (2 ** (attempt - 1)), max_wait)
    return wait * (0.5 + random.random() * 0.5)


class ProviderRecovery:
    """Recovery strategy wrapping provider operations with retry and backoff.

    Usage::

        recovery = ProviderRecovery(max_retries=3)
        result = await recovery.try_call(
            provider_id="deepseek",
            operation=lambda: provider.list_model_infos(),
            on_success=registry.record_provider_success,
            on_failure=registry.record_provider_failure,
        )
        if result.success:
            models = result.value
    """

    def __init__(self, max_retries: int = 3):
        self.max_retries = max_retries

    async def try_call(
        self,
        *,
        provider_id: str,
        operation: Callable[[], Awaitable[Any]],
        on_success: Callable[[str], None] | None = None,
        on_failure: Callable[[str, BaseException], None] | None = None,
    ) -> RecoveryResult:
        """Execute an async provider operation with retry and backoff.

        Args:
            provider_id: Identifier for logging and health tracking.
            operation: The async callable to execute.
            on_success: Called with provider_id on success — e.g. to reset
                the circuit breaker.
            on_failure: Called with (provider_id, exception) on each failure
                — e.g. to increment failure counters.

        Returns:
            RecoveryResult with success flag, value or error, and metadata.
        """
        start = time.perf_counter()
        last_error: BaseException | None = None
        decisions: list[RecoveryDecision] = []

        for attempt in range(1, self.max_retries + 2):
            try:
                value = await operation()
                elapsed = (time.perf_counter() - start) * 1000.0
                if on_success is not None:
                    on_success(provider_id)
                if attempt > 1:
                    logger.info(
                        "Provider recovery: {} succeeded on attempt {} ({}ms)",
                        provider_id, attempt, round(elapsed),
                    )
                return RecoveryResult(
                    success=True, value=value, attempts=attempt,
                    elapsed_ms=round(elapsed, 1),
                )
            except asyncio.CancelledError:
                raise
            except BaseException as exc:
                last_error = exc
                error_class = classify_error(exc)
                if on_failure is not None:
                    on_failure(provider_id, exc)

                if attempt > self.max_retries or error_class == ErrorClass.FATAL:
                    d = RecoveryDecision(
                        provider_id=provider_id,
                        error_type=type(exc).__name__,
                        error_class=error_class,
                        action=RecoveryAction.ESCALATE if error_class == ErrorClass.FATAL else RecoveryAction.SKIP,
                        attempt=attempt,
                        max_retries=self.max_retries,
                        backoff_seconds=0.0,
                        reason="fatal error" if error_class == ErrorClass.FATAL else "retries exhausted",
                    )
                else:
                    wait = _backoff(attempt)
                    d = RecoveryDecision(
                        provider_id=provider_id,
                        error_type=type(exc).__name__,
                        error_class=error_class,
                        action=RecoveryAction.RETRY,
                        attempt=attempt,
                        max_retries=self.max_retries,
                        backoff_seconds=round(wait, 2),
                        reason=str(exc)[:200],
                    )
                decisions.append(d)
                logger.warning(
                    "Provider recovery: {} attempt {}/{} — {}: {} → {} ({:.1f}s backoff)",
                    provider_id, attempt, self.max_retries + 1,
                    type(exc).__name__, error_class.name, d.action.name,
                    d.backoff_seconds,
                )

                if d.action == RecoveryAction.ESCALATE:
                    break
                if d.action == RecoveryAction.RETRY and attempt <= self.max_retries:
                    await asyncio.sleep(wait)

        elapsed = (time.perf_counter() - start) * 1000.0
        final_action = decisions[-1].action if decisions else RecoveryAction.ESCALATE
        return RecoveryResult(
            success=False,
            error=last_error,
            error_class=classify_error(last_error) if last_error else ErrorClass.FATAL,
            action=final_action,
            attempts=attempt if last_error else 1,
            elapsed_ms=round(elapsed, 1),
            detail=str(last_error)[:300] if last_error else "unknown",
        )
