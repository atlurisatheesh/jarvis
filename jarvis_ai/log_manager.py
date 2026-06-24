"""Centralized log management: rotation, token redaction, structured format.

Phase 0 reliability layer. Every log line passes through :func:`redact` so API
keys, OAuth tokens, passwords, and app passwords never reach disk. Logs are
retained for a bounded number of days (:data:`config.LOG_RETENTION_DAYS`) and
rotated when they exceed a size cap.

Usage::

    from jarvis_ai.log_manager import log, redact

    log("[startup] voice loop ready")          # writes to logs/leha.log
    safe = redact("Authorization: Bearer sk-abc123")  # -> "Authorization: Bearer [REDACTED]"
"""
from __future__ import annotations

import datetime as _dt
import os
import re
import threading
from pathlib import Path

from . import config

# ---------------------------------------------------------------------------
# Configuration (resolved lazily so config.py can import this safely)
# ---------------------------------------------------------------------------

def _log_dir() -> Path:
    d = Path(getattr(config, "LOG_DIR", "") or (config.BASE_DIR.parent / "logs"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _log_path() -> Path:
    return _log_dir() / getattr(config, "LOG_FILE_NAME", "leha.log")


def _retention_days() -> int:
    return int(getattr(config, "LOG_RETENTION_DAYS", 7))


def _max_bytes() -> int:
    return int(getattr(config, "LOG_MAX_SIZE_MB", 10)) * 1024 * 1024


# ---------------------------------------------------------------------------
# Token / secret redaction
# ---------------------------------------------------------------------------

# Match "Bearer <token>", "Token <token>", "key=<value>", "password=<value>",
# JSON-ish "api_key": "..." etc.  We redact the secret portion, not the label,
# so logs remain readable.
_SECRET_LABELS = (
    "authorization", "token", "apikey", "api_key", "password", "secret",
    "app_password", "access_key", "access_token", "refresh_token",
    "x-leha-pin", "web_pin", "groq_api_key", "openai_api_key",
    "deepgram_api_key", "cloudflare_api_token", "tg_token", "hf_token",
)

# Common long-secret shapes: bearer tokens, Google OAuth tokens, long hex/base64.
_BEARER_RE = re.compile(
    r"(?i)(bearer|token)\s+([A-Za-z0-9_\-\.=]{12,})",
)
_KEYVAL_RE = re.compile(
    r"(?i)(" + "|".join(_SECRET_LABELS) + r")\s*[:=]\s*[\"']?([A-Za-z0-9_\-\.\/\+]{8,})[\"']?",
)
# Standalone "ya29." Google tokens and long base64 JWTs.
_JWT_RE = re.compile(r"(ya29\.[A-Za-z0-9_\-]{20,}|eyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,})")
# 16-char Gmail app passwords (xxxx xxxx xxxx xxxx).
_APPPW_RE = re.compile(r"\b([A-Za-z0-9]{4}-?){4}\b")

_REDACTED = "[REDACTED]"


def redact(text: str) -> str:
    """Return *text* with likely secrets replaced by ``[REDACTED]``.

    Conservative by design: only redacts substrings that strongly resemble
    secrets (long opaque strings after known labels). Short values are kept so
    diagnostic output stays useful.
    """
    if not text:
        return text
    out = _BEARER_RE.sub(lambda m: f"{m.group(1)} {_REDACTED}", text)
    out = _KEYVAL_RE.sub(lambda m: f"{m.group(1)}={_REDACTED}", out)
    out = _JWT_RE.sub(_REDACTED, out)
    out = _APPPW_RE.sub(_REDACTED, out)
    return out


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

_write_lock = threading.Lock()


def _timestamp() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(message: str, *, component: str = "", level: str = "INFO", also_print: bool = True) -> None:
    """Append a structured, redacted log line.

    Format: ``YYYY-MM-DD HH:MM:SS LEVEL [component] message``
    """
    safe = redact(str(message))
    comp = f"[{component}] " if component else ""
    line = f"{_timestamp()} {level:<5} {comp}{safe}"
    if also_print:
        print(line, flush=True)
    try:
        path = _log_path()
        if path.exists() and path.stat().st_size > _max_bytes():
            _rotate(path)
        with _write_lock:
            with open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:
        # Logging must never crash the voice loop.
        pass


def _rotate(path: Path) -> None:
    """Rotate *path* to ``path.1`` and trim files older than retention."""
    backup = path.with_suffix(path.suffix + ".1")
    try:
        if backup.exists():
            backup.unlink()
        path.rename(backup)
    except OSError:
        pass
    cleanup_old_logs()


def cleanup_old_logs() -> int:
    """Delete rotated log files older than :data:`config.LOG_RETENTION_DAYS`.

    Returns the number of files removed.
    """
    removed = 0
    cutoff = _dt.datetime.now().timestamp() - _retention_days() * 86400
    for f in _log_dir().glob("*.log*"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
                removed += 1
        except OSError:
            pass
    return removed


def read_recent(path: Path | None = None, count: int = 200) -> list[str]:
    """Return the last *count* lines of the log (redacted already on write)."""
    path = path or _log_path()
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return lines[-count:]
    except OSError:
        return []
