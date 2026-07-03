"""Proactive notification queue for Leha.

The notifier is intentionally small: it never creates its own TTS engine.
Instead, the live listener registers the existing SpeechManager/Mouth as the
speaker, so reminders and background jobs use the same single voice queue.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from datetime import datetime

from . import config

_lock = threading.RLock()
_pending: deque[dict] = deque(maxlen=getattr(config, "NOTIFIER_MAX_QUEUE", 50))
_spoken_times: deque[float] = deque(maxlen=200)
_speaker = None


def _parse_hhmm(value: str) -> int | None:
    try:
        h, m = (value or "").split(":", 1)
        return int(h) * 60 + int(m)
    except Exception:
        return None


def _in_quiet_hours(now: datetime | None = None) -> bool:
    start = _parse_hhmm(getattr(config, "PROACTIVE_QUIET_HOURS_START", ""))
    end = _parse_hhmm(getattr(config, "PROACTIVE_QUIET_HOURS_END", ""))
    if start is None or end is None or start == end:
        return False
    now = now or datetime.now()
    minute = now.hour * 60 + now.minute
    if start < end:
        return start <= minute < end
    return minute >= start or minute < end


def _spoken_limit_reached(now: float | None = None) -> bool:
    now = now or time.time()
    window_start = now - 3600
    with _lock:
        while _spoken_times and _spoken_times[0] < window_start:
            _spoken_times.popleft()
        return len(_spoken_times) >= int(getattr(config, "PROACTIVE_MAX_SPOKEN_PER_HOUR", 8))


def should_speak(source: str = "system", *, important: bool = False) -> bool:
    """Return whether a proactive notification should be spoken aloud."""
    if important:
        return True
    if _in_quiet_hours():
        return False
    if _spoken_limit_reached():
        return False
    if source.startswith("job:") and not getattr(config, "PROACTIVE_SPEAK_BACKGROUND_JOBS", True):
        return False
    if getattr(config, "PROACTIVE_SPEAK_ONLY_USEFUL", True):
        low = source.lower()
        allowed = ("reminder", "timer", "calendar", "alarm", "job:")
        return any(part in low for part in allowed)
    return True


def register_speaker(speaker) -> None:
    """Register the central speech object. It must expose ``say(text)``."""
    global _speaker
    with _lock:
        _speaker = speaker


def unregister_speaker(speaker=None) -> None:
    global _speaker
    with _lock:
        if speaker is None or _speaker is speaker:
            _speaker = None


def notify(text: str, *, source: str = "system", speak: bool = True, important: bool = False) -> bool:
    """Queue a notification and optionally speak it through the registered speaker."""
    text = (text or "").strip()
    if not text or not getattr(config, "NOTIFIER_ENABLED", True):
        return False
    item = {"text": text, "source": source, "ts": time.time(), "spoken": False}
    with _lock:
        _pending.append(item)
        speaker = _speaker
    can_speak = speak and speaker is not None and should_speak(source, important=important)
    if can_speak:
        try:
            speaker.say(text)
            item["spoken"] = True
            with _lock:
                _spoken_times.append(time.time())
        except Exception:
            pass
    return True


def notify_background_done(name: str, result: str | None) -> None:
    """Short spoken completion for background jobs."""
    result = (result or "").strip()
    if result:
        if len(result) > 180:
            result = result[:177].rstrip() + "..."
        text = f"{name} is done. {result}"
    else:
        text = f"{name} is done, Sir."
    notify(text, source=f"job:{name}", speak=True)


def notify_background_error(name: str, error: str) -> None:
    err = (error or "unknown error").strip()
    if len(err) > 120:
        err = err[:117].rstrip() + "..."
    notify(f"{name} failed: {err}", source=f"job:{name}", speak=True, important=True)


def pending(limit: int = 10) -> list[dict]:
    with _lock:
        return list(_pending)[-limit:]


def pending_summary(limit: int = 5) -> str:
    items = pending(limit)
    if not items:
        return "No notifications, Sir."
    return "Notifications: " + "; ".join(i["text"] for i in items[-limit:])


def clear() -> None:
    with _lock:
        _pending.clear()
        _spoken_times.clear()
