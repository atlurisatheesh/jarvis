"""In-memory LRU cache for skill results.

Caches the output of read-only skills (weather, system_info, calendar, etc.)
with a per-skill TTL to avoid repeated cloud/API calls within a short window.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict


# Default TTL per skill name (seconds).  Skills not listed use the default.
_DEFAULT_TTL = 120  # 2 minutes
_SKILL_TTLS: dict[str, int] = {
    "get_weather": 300,          # 5 min – weather doesn't change fast
    "system_info": 60,           # 1 min – CPU/RAM changes frequently
    "google_calendar_upcoming": 300,
    "google_gmail_search": 120,
    "google_drive_search": 300,
    "google_contacts_search": 600,  # 10 min – contacts rarely change
    "phone_status": 120,
    "unread_email": 60,
    "recent_email": 60,
    "list_reminders": 30,
    "list_timers": 15,
    "get_ip": 600,
    "list_wifi": 300,
}


class SkillCache:
    """Thread-safe LRU cache keyed on ``(skill_name, args_key)``."""

    def __init__(self, max_size: int = 128, default_ttl: int = _DEFAULT_TTL):
        self._cache: OrderedDict[str, dict] = OrderedDict()
        self._max_size = max_size
        self._default_ttl = default_ttl
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    @staticmethod
    def _args_key(args: dict | None) -> str:
        """Deterministic string key from an args dict."""
        if not args:
            return ""
        parts = []
        for k, v in sorted((args or {}).items()):
            parts.append(f"{k}={v!r}")
        return "&".join(parts)

    def _cache_key(self, name: str, args: dict | None) -> str:
        return f"{name}|{self._args_key(args)}"

    def _ttl_for(self, name: str) -> int:
        return _SKILL_TTLS.get(name, self._default_ttl)

    def get(self, name: str, args: dict | None = None) -> str | None:
        key = self._cache_key(name, args)
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                self._misses += 1
                return None
            if time.monotonic() - entry["ts"] > entry["ttl"]:
                del self._cache[key]
                self._misses += 1
                return None
            # Move to end (most recently used)
            self._cache.move_to_end(key)
            self._hits += 1
            return entry["value"]

    def put(self, name: str, value: str, args: dict | None = None):
        key = self._cache_key(name, args)
        entry = {"value": value, "ts": time.monotonic(), "ttl": self._ttl_for(name)}
        with self._lock:
            if key in self._cache:
                del self._cache[key]
            elif len(self._cache) >= self._max_size:
                self._cache.popitem(last=False)  # evict LRU
            self._cache[key] = entry

    def invalidate(self, name: str | None = None):
        """Invalidate all entries for *name*, or everything if *name* is None."""
        with self._lock:
            if name is None:
                self._cache.clear()
            else:
                to_remove = [k for k in self._cache if k.startswith(f"{name}|")]
                for k in to_remove:
                    del self._cache[k]

    @property
    def stats(self) -> dict:
        with self._lock:
            return {
                "size": len(self._cache),
                "max_size": self._max_size,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(self._hits / max(1, self._hits + self._misses), 3),
            }


# Module-level singleton
_cache: SkillCache | None = None


def get_cache() -> SkillCache:
    global _cache
    if _cache is None:
        _cache = SkillCache()
    return _cache
