"""Self-protecting barge-in: detect when Leha hears her own echoed voice.

Barge-in lets the user interrupt Leha mid-speech ("Leha, stop"). On an
echo-prone setup (laptop mic + laptop speakers) her own spoken reply can be
picked up by the mic and re-trigger her, creating a feedback loop of
self-interruptions.

This module tracks barge-in interruptions and, when the transcribed interrupt
text looks like Leha's recent spoken reply (echo self-trigger), counts it as a
false interruption. After a threshold of false interruptions inside a rolling
window, the caller disables barge-in for the rest of the session.

This makes barge-in safe to enable by default: it works well on a clean
headset/USB mic and degrades gracefully on an echo-prone setup.
"""
from __future__ import annotations

import time
from collections import deque

from . import config


class BargeInGuard:
    """Track barge-in interruptions and flag echo self-triggers."""

    def __init__(self):
        # Recent spoken replies (lowercased, truncated) for echo matching.
        self._recent_spoken: deque[str] = deque(maxlen=20)
        # Timestamps of echo self-trigger detections inside the rolling window.
        self._false_interrupts: deque[float] = deque()
        # Set True once we've auto-disabled barge-in for this session.
        self.disabled = False

    # -- spoken reply tracking ------------------------------------------------

    def record_spoken(self, text: str) -> None:
        """Remember a piece of text Leha spoke, for later echo matching."""
        t = (text or "").strip().lower()
        if t:
            self._recent_spoken.append(t[:200])

    # -- interruption classification -----------------------------------------

    def classify_interrupt(self, interrupt_text: str) -> bool:
        """Return True if *interrupt_text* looks like Leha's echoed own voice.

        Only call this for actual barge-in interruptions (wake word heard while
        speaking). Never call it for normal wake events.
        """
        t = (interrupt_text or "").strip().lower()
        if not t:
            return False
        # A genuine interrupt usually contains a command: "stop", "leha stop",
        # "pause", "cancel", etc. Anything longer that closely matches recent
        # spoken text is almost certainly an echo.
        stripped = t.replace("leha", "").replace("hey leha", "").strip()
        short_commands = {"stop", "pause", "cancel", "nevermind", "quit", "enough"}
        if stripped in short_commands:
            return False
        # Compare against recently spoken replies.
        for recent in self._recent_spoken:
            if self._similar(t, recent):
                return True
        return False

    @staticmethod
    def _similar(a: str, b: str) -> bool:
        """Cheap similarity check — shared word overlap beyond short commands."""
        wa = set(a.split())
        wb = set(b.split())
        if not wa or not wb:
            return False
        overlap = len(wa & wb)
        # Require a meaningful overlap (>= 3 shared words or >= 60% of the
        # smaller side). One-word collisions (e.g. "the") don't count.
        if overlap < 3:
            return False
        smaller = min(len(wa), len(wb))
        return overlap / smaller >= 0.6

    # -- rolling-window auto-disable -----------------------------------------

    def register_interrupt(self, interrupt_text: str) -> bool:
        """Record a barge-in interrupt. Returns True if barge-in should disable.

        Call this on every barge-in interrupt. When echo self-triggers exceed
        the configured limit inside the rolling window, ``disabled`` is set and
        this returns True so the caller can turn barge-in off.
        """
        if self.disabled or not getattr(config, "AUTO_DISABLE_BARGE_IN_ON_ECHO", True):
            return False
        if not self.classify_interrupt(interrupt_text):
            # Genuine interrupt — clear the recent false count so a single echo
            # followed by real usage doesn't trip the guard.
            self._false_interrupts.clear()
            return False
        now = time.monotonic()
        window = getattr(config, "BARGE_IN_ECHO_WINDOW_S", 60.0)
        limit = getattr(config, "BARGE_IN_ECHO_LIMIT", 2)
        # Drop timestamps outside the window.
        while self._false_interrupts and now - self._false_interrupts[0] > window:
            self._false_interrupts.popleft()
        self._false_interrupts.append(now)
        if len(self._false_interrupts) >= limit:
            self.disabled = True
            self._false_interrupts.clear()
            return True
        return False

    def reset(self) -> None:
        """Clear all tracking state (e.g. for tests)."""
        self._recent_spoken.clear()
        self._false_interrupts.clear()
        self.disabled = False
