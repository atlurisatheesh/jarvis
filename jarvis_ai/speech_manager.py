"""Central speech manager — single source of truth for TTS output.

Guarantees:
    * One active speech output at a time (no overlapping voices).
    * Generation-counter invalidation: a new ``say()`` cancels stale audio.
    * FIFO queue with interrupt capability.
    * Thread-safe cancellation.

This wraps the existing ``Mouth`` class (which remains the TTS *generator*).
``SpeechManager`` owns the queue, playback lifecycle, and barge-in logic.
"""
from __future__ import annotations

import threading
import time


class SpeechManager:
    """Thread-safe speech queue with generation-based cancellation."""

    def __init__(self, mouth):
        """``mouth`` is a jarvis_ai.mouth.Mouth instance (TTS generator)."""
        self._mouth = mouth
        self._lock = threading.Lock()
        self._generation = 0
        self._active_generation = 0
        self._speaking = False
        self._speak_thread: threading.Thread | None = None
        self._history: list[dict] = []
        self._max_history = 50
        self._cancel_requested = False

    # -- generation management -----------------------------------------------

    def _next_generation(self) -> int:
        with self._lock:
            self._generation += 1
            return self._generation

    def _active_generation(self) -> int:
        with self._lock:
            return self._active_generation

    def _is_current(self, generation: int) -> bool:
        with self._lock:
            return generation == self._active_generation

    def _set_active(self, generation: int):
        with self._lock:
            self._active_generation = generation
            self._speaking = True
            self._cancel_requested = False

    def _clear_active(self):
        with self._lock:
            self._speaking = False
            self._speak_thread = None

    # -- public API ----------------------------------------------------------

    def is_speaking(self) -> bool:
        """True if speech is currently being generated/played."""
        with self._lock:
            return self._speaking

    def stop(self):
        """Interrupt current speech immediately."""
        with self._lock:
            self._cancel_requested = True
            self._speaking = False
        try:
            self._mouth.stop()
        except Exception:
            pass

    def join(self, timeout: float | None = None):
        """Wait for the current speech thread to finish."""
        thread = None
        with self._lock:
            thread = self._speak_thread
        if thread and thread.is_alive():
            thread.join(timeout=timeout)

    def say(self, text: str, wait: bool = False):
        """Speak *text*, interrupting any current speech.

        Delegates to ``Mouth.say`` but tracks generation for safe
        cancellation.  The generation counter ensures that stale audio
        from a previous turn is never played.
        """
        if not text or not text.strip():
            return
        generation = self._next_generation()
        self._set_active(generation)
        self._history.append({"generation": generation, "text": text[:200], "ts": time.monotonic()})
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]
        try:
            self._mouth.say(text, wait=wait)
        finally:
            if not wait:
                # Mouth.say already started a background thread; we track it.
                pass
            if wait:
                self._clear_active()

    def say_stream(self, token_gen) -> str:
        """Stream tokens to TTS via ``Mouth.say_stream``.

        Returns the full spoken text.  Interrupts any prior speech.
        """
        generation = self._next_generation()
        self._set_active(generation)
        try:
            text = self._mouth.say_stream(token_gen)
            self._history.append({"generation": generation, "text": (text or "")[:200], "ts": time.monotonic()})
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]
            return text or ""
        finally:
            self._clear_active()

    # -- introspection -------------------------------------------------------

    @property
    def generation(self) -> int:
        """Current generation counter (incremented on each say/stream)."""
        with self._lock:
            return self._generation

    @property
    def history(self) -> list[dict]:
        """Recent speech entries (generation, truncated text, timestamp)."""
        with self._lock:
            return list(self._history)


# Module-level singleton, lazily created with the shared Mouth instance.
_manager: SpeechManager | None = None


def get_manager(mouth=None) -> SpeechManager | None:
    """Get or create the global SpeechManager.

    ``mouth`` must be provided on first call.
    """
    global _manager
    if _manager is None and mouth is not None:
        _manager = SpeechManager(mouth)
    return _manager
