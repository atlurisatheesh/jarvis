"""Small in-process status registry for the always-on Leha listener."""
from __future__ import annotations

import threading
import time


class RuntimeState:
    def __init__(self):
        self._lock = threading.Lock()
        self._state = "starting"
        self._detail = ""
        self._updated_at = time.time()
        self._last_error = ""
        self._turns = 0
        self._timings: dict[str, float] = {}
        self._last_provider = ""

    def set(self, state: str, detail: str = ""):
        with self._lock:
            self._state = state
            self._detail = detail
            self._updated_at = time.time()

    def error(self, detail: str):
        with self._lock:
            self._state = "error"
            self._detail = detail
            self._last_error = detail
            self._updated_at = time.time()

    def turn_completed(self):
        with self._lock:
            self._turns += 1
            self._updated_at = time.time()

    def timing(self, stage: str, milliseconds: float):
        with self._lock:
            self._timings[stage] = round(milliseconds, 1)

    def begin_turn(self):
        with self._lock:
            self._timings = {}
            self._last_provider = ""

    def provider(self, name: str):
        with self._lock:
            self._last_provider = name

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "state": self._state,
                "detail": self._detail,
                "age_seconds": round(time.time() - self._updated_at, 1),
                "turns": self._turns,
                "last_error": self._last_error,
                "timings_ms": dict(self._timings),
                "last_provider": self._last_provider,
            }

    def latency_line(self) -> str:
        snapshot = self.snapshot()
        timings = snapshot["timings_ms"]
        pieces = [f"{name}={value}ms" for name, value in timings.items()]
        provider = snapshot["last_provider"] or "local"
        return f"[latency] provider={provider} " + " ".join(pieces)


runtime = RuntimeState()
