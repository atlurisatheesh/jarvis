"""Per-provider circuit breaker.

States:
    CLOSED   – normal operation, requests pass through.
    OPEN     – provider is failing, all requests are rejected immediately.
    HALF_OPEN – one probe request is allowed to test recovery.

Transitions:
    CLOSED → OPEN     after ``failure_threshold`` consecutive failures.
    OPEN → HALF_OPEN  after ``open_seconds`` of cooldown.
    HALF_OPEN → CLOSED on the first successful probe.
    HALF_OPEN → OPEN   if the probe fails.
"""
from __future__ import annotations

import enum
import threading
import time


class _State(enum.Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Thread-safe circuit breaker for a single cloud provider."""

    def __init__(
        self,
        name: str,
        failure_threshold: int = 3,
        open_seconds: float = 45.0,
        half_open_seconds: float = 30.0,
    ):
        self.name = name
        self.failure_threshold = max(1, failure_threshold)
        self.open_seconds = open_seconds
        self.half_open_seconds = half_open_seconds

        self._state = _State.CLOSED
        self._consecutive_failures = 0
        self._opened_at: float = 0.0
        self._total_failures: int = 0
        self._total_successes: int = 0
        self._lock = threading.Lock()

    # -- public query methods ------------------------------------------------

    @property
    def state(self) -> str:
        with self._lock:
            self._maybe_transition()
            return self._state.value

    def allow_request(self) -> bool:
        """Return True if the provider should be tried."""
        with self._lock:
            self._maybe_transition()
            return self._state in (_State.CLOSED, _State.HALF_OPEN)

    def record_success(self):
        with self._lock:
            self._total_successes += 1
            self._consecutive_failures = 0
            if self._state == _State.HALF_OPEN:
                self._state = _State.CLOSED

    def record_failure(self):
        with self._lock:
            self._total_failures += 1
            self._consecutive_failures += 1
            if self._state == _State.HALF_OPEN:
                # Probe failed – go back to OPEN
                self._state = _State.OPEN
                self._opened_at = time.monotonic()
            elif self._consecutive_failures >= self.failure_threshold:
                self._state = _State.OPEN
                self._opened_at = time.monotonic()

    def reset(self):
        """Manually reset to CLOSED (e.g. after config change)."""
        with self._lock:
            self._state = _State.CLOSED
            self._consecutive_failures = 0

    @property
    def stats(self) -> dict:
        with self._lock:
            self._maybe_transition()
            return {
                "name": self.name,
                "state": self._state.value,
                "consecutive_failures": self._consecutive_failures,
                "total_failures": self._total_failures,
                "total_successes": self._total_successes,
            }

    # -- internal ------------------------------------------------------------

    def _maybe_transition(self):
        """Auto-transition from OPEN → HALF_OPEN after cooldown."""
        if self._state == _State.OPEN:
            elapsed = time.monotonic() - self._opened_at
            if elapsed >= self.open_seconds:
                self._state = _State.HALF_OPEN
