"""Audit log for all tool executions.

Writes JSON-lines format to ``memory_store/audit.logl``.  Records:
    timestamp, tool name, args (redacted), origin, result summary, latency.

Sensitive argument values (passwords, tokens, messages) are redacted.
Log rotation happens when the file exceeds ``AUDIT_LOG_MAX_SIZE_MB``.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from . import config


# Argument keys whose values should be redacted in the audit log.
_SENSITIVE_KEYS = {
    "password", "token", "secret", "key", "api_key", "pin",
    "message", "body", "text",  # message contents are private
    "command",  # shell commands can contain secrets
}


def _redact_args(args: dict | None) -> dict:
    """Return a copy of *args* with sensitive values redacted."""
    if not args:
        return {}
    redacted = {}
    for k, v in args.items():
        if k.lower() in _SENSITIVE_KEYS:
            redacted[k] = "***REDACTED***"
        elif isinstance(v, str) and len(v) > 200:
            redacted[k] = v[:200] + "..."
        else:
            redacted[k] = v
    return redacted


def _truncate_result(result: str | None, max_chars: int = 300) -> str:
    if not result:
        return ""
    if len(result) > max_chars:
        return result[:max_chars] + "..."
    return result


class AuditLog:
    """Thread-safe JSON-lines audit logger."""

    def __init__(self, log_path: str | Path | None = None, max_size_mb: int = 50):
        if log_path is None:
            log_path = Path(config.MEMORY_DIR) / "audit.logl"
        self._path = Path(log_path)
        self._max_bytes = max_size_mb * 1024 * 1024
        self._lock = threading.Lock()

    def log(
        self,
        tool: str,
        args: dict | None,
        origin: str,
        result: str | None,
        latency_ms: float = 0.0,
        error: str | None = None,
    ):
        """Append an audit entry."""
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "tool": tool,
            "args": _redact_args(args),
            "origin": origin,
            "result": _truncate_result(result),
            "latency_ms": round(latency_ms, 1),
            "error": error,
        }
        line = json.dumps(entry, ensure_ascii=False)
        with self._lock:
            self._rotate_if_needed()
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(line + "\n")

    def _rotate_if_needed(self):
        """Rotate the log if it exceeds max size."""
        try:
            if not self._path.exists():
                return
            if self._path.stat().st_size < self._max_bytes:
                return
        except OSError:
            return
        # Simple rotation: rename to .1 and start fresh
        backup = self._path.with_suffix(".logl.1")
        try:
            if backup.exists():
                backup.unlink()
            self._path.rename(backup)
        except OSError:
            pass

    def read_recent(self, count: int = 50) -> list[dict]:
        """Read the last *count* entries from the log."""
        if not self._path.exists():
            return []
        entries = []
        with self._lock:
            try:
                lines = self._path.read_text(encoding="utf-8").strip().split("\n")
            except OSError:
                return []
        for line in lines[-count:]:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return entries

    def search(self, tool: str | None = None, origin: str | None = None) -> list[dict]:
        """Search audit entries by tool name or origin."""
        entries = self.read_recent(count=10000)
        if tool:
            entries = [e for e in entries if e.get("tool") == tool]
        if origin:
            entries = [e for e in entries if e.get("origin") == origin]
        return entries


# Module-level singleton
_audit: AuditLog | None = None


def get_audit_log() -> AuditLog:
    global _audit
    if _audit is None:
        max_mb = getattr(config, "AUDIT_LOG_MAX_SIZE_MB", 50)
        _audit = AuditLog(max_size_mb=max_mb)
    return _audit


def log_tool(tool: str, args: dict | None, origin: str, result: str | None,
             latency_ms: float = 0.0, error: str | None = None):
    """Convenience function to log a tool execution."""
    if not getattr(config, "AUDIT_LOG_ENABLED", True):
        return
    get_audit_log().log(tool, args, origin, result, latency_ms, error)
