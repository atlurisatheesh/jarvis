"""Latency budget tracker for the voice pipeline.

Defines acceptable time budgets for each stage and logs overruns.

Stage budgets (seconds):
    wake           < 0.5
    capture        0.3 – 0.8
    stt            < 1.0
    local_intent   < 0.1
    first_token    < 1.5   (cloud brain)
    tts_generate   < 0.5
    turn_dispatch  < 3.0   (full end-to-end)
"""
from __future__ import annotations

import time
import threading

# Default budgets in seconds per pipeline stage.
DEFAULT_BUDGETS: dict[str, float] = {
    "wake": 0.5,
    "capture": 0.8,
    "stt": 1.0,
    "local_intent": 0.1,
    "first_token": 1.5,
    "brain_total": 4.0,
    "tts_generate": 0.5,
    "turn_dispatch": 3.0,
}

# Stages that should *always* be tracked.
TRACKED_STAGES = set(DEFAULT_BUDGETS.keys())


class LatencyBudget:
    """Track per-stage latency against configured budgets."""

    def __init__(self, budgets: dict[str, float] | None = None):
        self._budgets = dict(budgets or DEFAULT_BUDGETS)
        self._history: list[dict] = []
        self._lock = threading.Lock()
        self._overruns: dict[str, int] = {k: 0 for k in self._budgets}

    @property
    def budgets(self) -> dict[str, float]:
        return dict(self._budgets)

    def set_budget(self, stage: str, seconds: float):
        """Update a budget at runtime."""
        with self._lock:
            self._budgets[stage] = seconds
            if stage not in self._overruns:
                self._overruns[stage] = 0

    def record(self, stage: str, elapsed: float):
        """Record a latency measurement and check the budget."""
        budget = self._budgets.get(stage)
        entry = {
            "stage": stage,
            "elapsed": round(elapsed, 4),
            "budget": round(budget, 4) if budget is not None else None,
            "over": False,
        }
        if budget is not None and elapsed > budget:
            entry["over"] = True
            self._overruns[stage] = self._overruns.get(stage, 0) + 1
        with self._lock:
            self._history.append(entry)
            # Keep last 200 entries
            if len(self._history) > 200:
                self._history = self._history[-200:]

    class StageTimer:
        """Context manager that records latency on exit."""

        def __init__(self, tracker: "LatencyBudget", stage: str):
            self._tracker = tracker
            self._stage = stage
            self._start: float = 0.0

        def __enter__(self):
            self._start = time.monotonic()
            return self

        def __exit__(self, *exc):
            elapsed = time.monotonic() - self._start
            self._tracker.record(self._stage, elapsed)

    def timer(self, stage: str) -> "StageTimer":
        """Return a context-manager timer for *stage*."""
        return self.StageTimer(self, stage)

    @property
    def overruns(self) -> dict[str, int]:
        with self._lock:
            return dict(self._overruns)

    def summary(self, last_n: int = 20) -> str:
        """Human-readable summary of recent measurements."""
        with self._lock:
            recent = self._history[-last_n:]
        if not recent:
            return "No latency data."
        lines = ["[latency] recent pipeline stages:"]
        for entry in recent:
            flag = " ⚠ OVER" if entry["over"] else ""
            budget_str = f"/{entry['budget']:.3f}s" if entry["budget"] else ""
            lines.append(
                f"  {entry['stage']:15s}  {entry['elapsed']:.3f}s{budget_str}{flag}"
            )
        return "\n".join(lines)


# Module-level singleton, lazily created. Mirrors the get_manager /
# get_background_jobs pattern so the listener and tests share one tracker.
_budget: LatencyBudget | None = None


def get_latency_budget() -> LatencyBudget:
    """Get or create the global LatencyBudget singleton."""
    global _budget
    if _budget is None:
        _budget = LatencyBudget()
    return _budget
