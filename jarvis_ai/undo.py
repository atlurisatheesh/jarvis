"""Undo stack for reversible system actions.

Tracks changes to volume, brightness, theme, window layout, etc.
``Leha undo`` pops and reverses the last action.

Each entry has a ``rollback()`` callable that restores the prior state.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class UndoEntry:
    """A single reversible action."""
    description: str
    rollback: Callable[[], str]  # returns a status message
    category: str = "general"    # volume | brightness | theme | windows | general
    created_at: float = field(default_factory=lambda: __import__("time").monotonic())


class UndoStack:
    """Thread-safe LIFO undo stack."""

    def __init__(self, max_depth: int = 20):
        self._stack: list[UndoEntry] = []
        self._max_depth = max_depth
        self._lock = threading.Lock()

    def push(self, description: str, rollback: Callable[[], str], category: str = "general"):
        """Record a reversible action."""
        entry = UndoEntry(description=description, rollback=rollback, category=category)
        with self._lock:
            self._stack.append(entry)
            if len(self._stack) > self._max_depth:
                self._stack = self._stack[-self._max_depth:]

    def undo_last(self, category: str | None = None) -> str:
        """Undo the most recent action (optionally filtered by category).

        Returns a status message, or "Nothing to undo" if the stack is empty.
        """
        with self._lock:
            if not self._stack:
                return "Nothing to undo, Sir."
            if category:
                # Find the most recent entry in this category
                for i in range(len(self._stack) - 1, -1, -1):
                    if self._stack[i].category == category:
                        entry = self._stack.pop(i)
                        break
                else:
                    return f"Nothing to undo in {category}, Sir."
            else:
                entry = self._stack.pop()
        try:
            result = entry.rollback()
            return f"Undid: {entry.description}. {result}"
        except Exception as exc:
            return f"Could not undo '{entry.description}': {exc}"

    def undo_all(self, category: str | None = None) -> str:
        """Undo all actions (optionally in a category)."""
        count = 0
        while True:
            result = self.undo_last(category)
            if "Nothing to undo" in result:
                break
            count += 1
            if count > 20:
                break
        if count == 0:
            return "Nothing to undo, Sir."
        return f"Undid {count} actions, Sir."

    @property
    def depth(self) -> int:
        with self._lock:
            return len(self._stack)

    @property
    def recent(self) -> list[dict]:
        """Return the last 10 undoable actions (most recent first)."""
        with self._lock:
            return [
                {"description": e.description, "category": e.category}
                for e in reversed(self._stack[-10:])
            ]

    def clear(self):
        with self._lock:
            self._stack.clear()


# Module-level singleton
_undo: UndoStack | None = None


def get_undo_stack() -> UndoStack:
    global _undo
    if _undo is None:
        _undo = UndoStack()
    return _undo


def record_volume_change(old_level: int, new_level: int):
    """Helper: record a volume change for undo."""
    def rollback():
        from .skills import system
        diff = old_level - new_level
        direction = "up" if diff > 0 else "down"
        system.set_volume(direction=direction, steps=abs(diff))
        return f"Volume restored to {old_level}%."
    get_undo_stack().push(f"volume {new_level}%", rollback, category="volume")


def record_brightness_change(old_pct: int, new_pct: int):
    """Helper: record a brightness change for undo."""
    def rollback():
        from .skills import windows as win_skills
        win_skills.set_brightness(percent=old_pct)
        return f"Brightness restored to {old_pct}%."
    get_undo_stack().push(f"brightness {new_pct}%", rollback, category="brightness")


def record_theme_change(old_dark: bool, new_dark: bool):
    """Helper: record a dark/light mode toggle for undo."""
    def rollback():
        from .skills import windows as win_skills
        win_skills.dark_mode(enable=old_dark)
        return f"Theme restored to {'dark' if old_dark else 'light'}."
    get_undo_stack().push(f"{'dark' if new_dark else 'light'} mode", rollback, category="theme")
