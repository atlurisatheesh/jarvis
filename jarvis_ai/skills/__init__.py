"""Skill registry. Each skill module exposes SKILLS = [(schema, fn), ...].

`TOOLS` is the list of tool schemas handed to the LLM.
`run_tool(name, args)` dispatches a tool call to the matching function.
"""
from __future__ import annotations

import contextvars

from .. import config
from . import (system, files, web, media, notes, phone,
               reminders, routines, desktop, docs, farm, universal, timer, windows,
               vision, context, email, google)

_modules = [system, files, web, media, notes, phone,
            reminders, routines, desktop, docs, farm, universal, timer, windows,
            vision, context, email, google]

TOOLS = []          # Ollama/OpenAI-style tool schemas
DISPATCH = {}       # name -> python function

for _m in _modules:
    for _schema, _fn in _m.SKILLS:
        TOOLS.append({"type": "function", "function": _schema})
        DISPATCH[_schema["name"]] = _fn

# Phase 7: Home Assistant skills (graceful "not configured" when no token).
try:
    from .. import home_assistant as _ha
    for _schema, _fn in _ha.SKILLS:
        TOOLS.append({"type": "function", "function": _schema})
        DISPATCH[_schema["name"]] = _fn
except Exception:
    pass

# Phase 8: structured memory skills (remember_this, what_do_you_remember,
# forget_that) plus an export_my_data convenience wrapper.
try:
    from .. import structured_memory as _sm

    def _export_my_data(**_kwargs) -> str:
        """Export all stored personal memories as JSON."""
        import json as _json
        data = _sm.export_all()
        if not data:
            return "No personal data stored, Sir."
        return _json.dumps(data, ensure_ascii=False, indent=2)

    for _schema, _fn in _sm.SKILLS:
        TOOLS.append({"type": "function", "function": _schema})
        DISPATCH[_schema["name"]] = _fn

    _export_schema = {
        "name": "export_my_data",
        "description": "Export all stored personal memories as JSON for review or backup.",
        "parameters": {"type": "object", "properties": {}},
    }
    TOOLS.append({"type": "function", "function": _export_schema})
    DISPATCH["export_my_data"] = _export_my_data
except Exception:
    pass


# ── Origin-based safety gate ──────────────────────────────────────────
# Voice on the laptop is trusted ("local"). Remote front ends (web/PWA,
# Telegram, phone app) are "remote" and must NOT be able to run a shell or
# destructive/outbound actions even if the brain tries to call them.
_origin = contextvars.ContextVar("leha_origin", default="local")
_confirmed = contextvars.ContextVar("leha_confirmed_tool", default=False)

# Tools refused for remote callers (shell, power, outbound cost/contact, net).
REMOTE_BLOCKED_TOOLS = {
    "run_command",
    "shutdown_pc", "restart_pc", "sleep_pc", "hibernate_pc", "logoff_pc",
    "kill_process", "eject_usb", "set_wallpaper", "toggle_wifi",
    "phone_call", "phone_send_sms", "phone_whatsapp",
    "google_gmail_send",
}


def set_origin(origin: str):
    """Mark the current request context as 'local' or 'remote'."""
    _origin.set("remote" if origin == "remote" else "local")


def get_origin() -> str:
    return _origin.get()


def run_confirmed_tool(name: str, args: dict) -> str:
    """Run a confirmation-required tool after the local voice gate approved it."""
    token = _confirmed.set(True)
    try:
        return run_tool(name, args)
    finally:
        _confirmed.reset(token)


# Read-only skills whose output can be safely cached (Phase 2).
_CACHEABLE_TOOLS = {
    "get_weather", "system_info", "google_calendar_upcoming", "google_gmail_search",
    "google_drive_search", "google_contacts_search", "phone_status", "unread_email",
    "recent_email", "list_reminders", "list_timers", "get_ip", "list_wifi",
}


def run_tool(name: str, args: dict) -> str:
    origin = _origin.get()
    # Legacy hard block on known-dangerous remote tools (kept for safety).
    if origin == "remote" and name in REMOTE_BLOCKED_TOOLS:
        return f"'{name}' is blocked for remote requests, Sir. Use it from the laptop."
    fn = DISPATCH.get(name)
    if not fn:
        return f"Unknown tool: {name}"

    # Phase 4: skill policy check.
    from .. import skill_policy
    policy = skill_policy.check(name, origin)
    if not policy.allowed:
        from .. import audit_log
        audit_log.log_tool(name, args, origin, None, error=policy.reason)
        return policy.reason
    if policy.needs_confirmation and not _confirmed.get():
        reason = f"Confirmation required before running '{name}', Sir."
        from .. import audit_log
        audit_log.log_tool(name, args, origin, None, error=reason)
        return reason

    # Phase 4: audit logging before execution.
    from .. import audit_log
    import time as _time
    _t0 = _time.perf_counter()

    # Phase 2: cache read-only skill results when enabled.
    cache = None
    if getattr(config, "SKILL_CACHE_ENABLED", False) and name in _CACHEABLE_TOOLS:
        try:
            from ..skill_cache import get_cache
            cache = get_cache()
            cached = cache.get(name, args)
            if cached is not None:
                audit_log.log_tool(name, args, origin, cached, latency_ms=0.0)
                return cached
        except Exception:
            cache = None
    try:
        result = str(fn(**(args or {})))
        if cache is not None:
            cache.put(name, result, args)
        latency = (_time.perf_counter() - _t0) * 1000
        audit_log.log_tool(name, args, origin, result, latency_ms=latency)
        return result
    except Exception as e:
        latency = (_time.perf_counter() - _t0) * 1000
        audit_log.log_tool(name, args, origin, None, latency_ms=latency, error=str(e))
        return f"Error running {name}: {e}"


def submit_background(
    name: str,
    fn: callable,
    on_done: callable | None = None,
    on_error: callable | None = None,
) -> object:
    """Run a slow skill action off the mic loop.

    When ``config.BACKGROUND_JOBS_ENABLED`` is True, *fn* is handed to the
    shared :class:`~jarvis_ai.background_jobs.BackgroundJobs` pool and a job id
    is returned. When disabled (or if the pool cannot be created), *fn* runs
    synchronously and its result is returned directly — identical to the
    pre-background behavior. This keeps the mic loop responsive without ever
    changing the result a caller would have received inline.
    """
    if not getattr(config, "BACKGROUND_JOBS_ENABLED", False):
        try:
            result = fn()
        except Exception as e:
            if on_error:
                try:
                    on_error(str(e))
                except Exception:
                    pass
            return None
        if on_done:
            try:
                on_done(result)
            except Exception:
                pass
        return result
    try:
        from ..background_jobs import get_background_jobs
        return get_background_jobs().submit(
            name, fn, on_done=on_done, on_error=on_error
        )
    except Exception:
        # Background pool unavailable — fall back to inline execution so the
        # skill still returns a result instead of failing.
        try:
            result = fn()
        except Exception as e:
            if on_error:
                try:
                    on_error(str(e))
                except Exception:
                    pass
            return None
        if on_done:
            try:
                on_done(result)
            except Exception:
                pass
        return result
