"""Persistent owner-tunable pro settings.

These settings are deliberately small and explicit. They let the dashboard
adjust pro-mode knobs without editing config.py directly. Values are applied at
import/startup time; live listener changes should be followed by a Leha restart.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from . import config

_PATH = Path(config.MEMORY_DIR) / "pro_settings.json"
_LOCK = threading.RLock()

DEFAULTS = {
    "custom_wake_threshold": float(getattr(config, "CUSTOM_WAKE_THRESHOLD", 0.995)),
    "barge_in_enabled": bool(getattr(config, "BARGE_IN_ENABLED", False)),
    "aec_enabled": bool(getattr(config, "AEC_ENABLED", False)),
    "proactive_max_spoken_per_hour": int(getattr(config, "PROACTIVE_MAX_SPOKEN_PER_HOUR", 8)),
    "quiet_hours_start": getattr(config, "PROACTIVE_QUIET_HOURS_START", "22:30"),
    "quiet_hours_end": getattr(config, "PROACTIVE_QUIET_HOURS_END", "07:00"),
}


def _coerce(data: dict) -> dict:
    out = dict(DEFAULTS)
    if not isinstance(data, dict):
        return out
    if "custom_wake_threshold" in data:
        try:
            out["custom_wake_threshold"] = max(0.50, min(0.9999, float(data["custom_wake_threshold"])))
        except Exception:
            pass
    for key in ("barge_in_enabled", "aec_enabled"):
        if key in data:
            out[key] = bool(data[key])
    if "proactive_max_spoken_per_hour" in data:
        try:
            out["proactive_max_spoken_per_hour"] = max(0, min(60, int(data["proactive_max_spoken_per_hour"])))
        except Exception:
            pass
    for key in ("quiet_hours_start", "quiet_hours_end"):
        if key in data:
            value = str(data[key]).strip()
            if len(value) == 5 and value[2] == ":":
                out[key] = value
    return out


def load() -> dict:
    with _LOCK:
        try:
            raw = json.loads(_PATH.read_text(encoding="utf-8"))
        except Exception:
            raw = {}
        return _coerce(raw)


def save(updates: dict) -> dict:
    with _LOCK:
        current = load()
        current.update(updates or {})
        data = _coerce(current)
        data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        _PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return data


def apply_to_config() -> dict:
    """Apply persisted settings to the current Python process."""
    data = load()
    config.CUSTOM_WAKE_THRESHOLD = float(data["custom_wake_threshold"])
    config.BARGE_IN_ENABLED = bool(data["barge_in_enabled"])
    config.AEC_ENABLED = bool(data["aec_enabled"])
    config.PROACTIVE_MAX_SPOKEN_PER_HOUR = int(data["proactive_max_spoken_per_hour"])
    config.PROACTIVE_QUIET_HOURS_START = str(data["quiet_hours_start"])
    config.PROACTIVE_QUIET_HOURS_END = str(data["quiet_hours_end"])
    return data
