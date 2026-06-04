"""Circuit-breaker health tracking for provider instances."""

from __future__ import annotations

import time
from dataclasses import dataclass

PROVIDER_CIRCUIT_FAILURE_THRESHOLD = 2
PROVIDER_CIRCUIT_COOLDOWN_SECONDS = 60.0


@dataclass(slots=True)
class ProviderHealth:
    """In-process health/circuit-breaker state for one provider."""

    provider_id: str
    status: str = "unknown"
    consecutive_failures: int = 0
    last_success_at: float | None = None
    last_failure_at: float | None = None
    last_error_type: str = ""
    circuit_open_until: float | None = None

    def is_available(self, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        if self.circuit_open_until is None:
            return True
        if self.circuit_open_until <= now:
            self.circuit_open_until = None
            self.status = "unknown"
            return True
        return False

    def snapshot(self, now: float | None = None) -> dict[str, object]:
        now = time.time() if now is None else now
        available = self.is_available(now)
        status = self.status
        if self.circuit_open_until is not None and self.circuit_open_until > now:
            status = "circuit_open"
        return {
            "provider_id": self.provider_id,
            "status": status,
            "available": available,
            "consecutive_failures": self.consecutive_failures,
            "last_success_at": self.last_success_at,
            "last_failure_at": self.last_failure_at,
            "last_error_type": self.last_error_type,
            "circuit_open_until": self.circuit_open_until,
        }
