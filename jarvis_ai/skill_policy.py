"""Skill policy engine.

Each skill/tool gets a policy defining:
    risk_level          – "read" | "reversible" | "external" | "destructive"
    sources_allowed     – set of {"local", "remote", "telegram", "android"}
    confirmation_required – bool (user must confirm before execution)
    timeout_seconds     – max execution time
    audit               – bool (log to audit trail)

``check(name, origin)`` returns a PolicyDecision that ``run_tool`` uses to
gate execution, request confirmation, or refuse the call.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SkillPolicy:
    risk_level: str = "read"  # read | reversible | external | destructive
    sources_allowed: set = field(default_factory=lambda: {"local", "remote", "telegram", "android"})
    confirmation_required: bool = False
    timeout_seconds: int = 120
    audit: bool = True


@dataclass
class PolicyDecision:
    allowed: bool
    needs_confirmation: bool = False
    reason: str = ""


# ---------------------------------------------------------------------------
# Default policy registry
# ---------------------------------------------------------------------------

# Risk-level classifications for all known tools.  Tools not listed here get
# a default "reversible" policy with full source access.
_DEFAULT_POLICIES: dict[str, SkillPolicy] = {
    # --- Read-only (safe from any source) ---
    "tell_time": SkillPolicy(risk_level="read", sources_allowed={"local", "remote", "telegram", "android"}),
    "system_info": SkillPolicy(risk_level="read"),
    "get_weather": SkillPolicy(risk_level="read"),
    "get_processes": SkillPolicy(risk_level="read"),
    "get_ip": SkillPolicy(risk_level="read"),
    "list_wifi": SkillPolicy(risk_level="read"),
    "list_reminders": SkillPolicy(risk_level="read"),
    "list_timers": SkillPolicy(risk_level="read"),
    "list_routines": SkillPolicy(risk_level="read"),
    "recall_facts": SkillPolicy(risk_level="read"),
    "phone_status": SkillPolicy(risk_level="read"),
    "phone_notifications": SkillPolicy(risk_level="read"),
    "phone_read_sms": SkillPolicy(risk_level="read"),
    "phone_unread_sms": SkillPolicy(risk_level="read"),
    "phone_screenshot": SkillPolicy(risk_level="read"),
    "phone_screen_dump": SkillPolicy(risk_level="read"),
    "read_screen": SkillPolicy(risk_level="read"),
    "read_clipboard": SkillPolicy(risk_level="read"),
    "see_screen": SkillPolicy(risk_level="read"),
    "search_files": SkillPolicy(risk_level="read"),
    "search_file_contents": SkillPolicy(risk_level="read"),
    "recent_files": SkillPolicy(risk_level="read"),
    "find_anything": SkillPolicy(risk_level="read"),
    "ask_docs": SkillPolicy(risk_level="read"),
    "google_calendar_upcoming": SkillPolicy(risk_level="read"),
    "google_gmail_search": SkillPolicy(risk_level="read"),
    "google_drive_search": SkillPolicy(risk_level="read"),
    "google_contacts_search": SkillPolicy(risk_level="read"),
    "home_assistant_ping": SkillPolicy(risk_level="read"),
    "home_assistant_list": SkillPolicy(risk_level="read"),
    "search_email": SkillPolicy(risk_level="read"),
    "recent_email": SkillPolicy(risk_level="read"),
    "unread_email": SkillPolicy(risk_level="read"),
    "fetch_page": SkillPolicy(risk_level="read"),
    "calculate": SkillPolicy(risk_level="read"),

    # --- Reversible (local only or with confirmation for remote) ---
    "open_app": SkillPolicy(risk_level="reversible"),
    "open_path": SkillPolicy(risk_level="reversible"),
    "open_url": SkillPolicy(risk_level="reversible"),
    "open_google_maps": SkillPolicy(risk_level="reversible"),
    "search_google_maps": SkillPolicy(risk_level="reversible"),
    "play_youtube": SkillPolicy(risk_level="reversible"),
    "media_play_pause": SkillPolicy(risk_level="reversible"),
    "media_next": SkillPolicy(risk_level="reversible"),
    "media_prev": SkillPolicy(risk_level="reversible"),
    "set_volume": SkillPolicy(risk_level="reversible"),
    "mute": SkillPolicy(risk_level="reversible"),
    "set_brightness": SkillPolicy(risk_level="reversible"),
    "dark_mode": SkillPolicy(risk_level="reversible"),
    "close_current_tab": SkillPolicy(risk_level="reversible"),
    "close_current_window": SkillPolicy(risk_level="reversible"),
    "close_app": SkillPolicy(risk_level="reversible"),
    "show_desktop": SkillPolicy(risk_level="reversible"),
    "minimize_all": SkillPolicy(risk_level="reversible"),
    "snap_window": SkillPolicy(risk_level="reversible"),
    "switch_to_app": SkillPolicy(risk_level="reversible"),
    "phone_open_app": SkillPolicy(risk_level="reversible"),
    "phone_force_stop_app": SkillPolicy(risk_level="reversible"),
    "phone_open_url": SkillPolicy(risk_level="reversible"),
    "phone_youtube_search": SkillPolicy(risk_level="reversible"),
    "phone_maps": SkillPolicy(risk_level="reversible"),
    "phone_key": SkillPolicy(risk_level="reversible"),
    "phone_type": SkillPolicy(risk_level="reversible"),
    "phone_tap": SkillPolicy(risk_level="reversible"),
    "phone_swipe": SkillPolicy(risk_level="reversible"),
    "phone_tap_text": SkillPolicy(risk_level="reversible"),
    "phone_ring": SkillPolicy(risk_level="reversible"),
    "set_clipboard": SkillPolicy(risk_level="reversible"),
    "type_text": SkillPolicy(risk_level="reversible"),
    "press_hotkey": SkillPolicy(risk_level="reversible"),
    "set_reminder": SkillPolicy(risk_level="reversible"),
    "set_timer": SkillPolicy(risk_level="reversible"),
    "remember_fact": SkillPolicy(risk_level="reversible"),
    "google_calendar_create": SkillPolicy(risk_level="reversible", confirmation_required=True),
    "home_assistant_turn_on": SkillPolicy(risk_level="reversible"),
    "home_assistant_turn_off": SkillPolicy(risk_level="reversible"),
    "home_assistant_scene": SkillPolicy(risk_level="reversible"),
    "farm_journal": SkillPolicy(risk_level="reversible"),
    "ingest_docs": SkillPolicy(risk_level="reversible"),
    "authorize_google": SkillPolicy(risk_level="reversible"),

    # --- External (sends data out, may cost money) ---
    "web_search": SkillPolicy(risk_level="external"),
    "phone_wifi_setup": SkillPolicy(risk_level="external"),
    "phone_wifi_reconnect": SkillPolicy(risk_level="external"),
    "google_gmail_send": SkillPolicy(risk_level="external", confirmation_required=True, sources_allowed={"local"}),
    "diagnose_leaf": SkillPolicy(risk_level="external"),

    # --- Destructive (local only, confirmation required) ---
    "run_command": SkillPolicy(risk_level="destructive", confirmation_required=False, sources_allowed={"local"}),
    "run_script": SkillPolicy(risk_level="destructive", sources_allowed={"local"}),
    "shutdown_pc": SkillPolicy(risk_level="destructive", confirmation_required=True, sources_allowed={"local"}),
    "restart_pc": SkillPolicy(risk_level="destructive", confirmation_required=True, sources_allowed={"local"}),
    "sleep_pc": SkillPolicy(risk_level="destructive", confirmation_required=True, sources_allowed={"local"}),
    "hibernate_pc": SkillPolicy(risk_level="destructive", confirmation_required=True, sources_allowed={"local"}),
    "logoff_pc": SkillPolicy(risk_level="destructive", confirmation_required=True, sources_allowed={"local"}),
    "kill_process": SkillPolicy(risk_level="destructive", confirmation_required=True, sources_allowed={"local"}),
    "eject_usb": SkillPolicy(risk_level="destructive", confirmation_required=True, sources_allowed={"local"}),
    "set_wallpaper": SkillPolicy(risk_level="destructive", sources_allowed={"local"}),
    "toggle_wifi": SkillPolicy(risk_level="destructive", confirmation_required=True, sources_allowed={"local"}),
    "lock_pc": SkillPolicy(risk_level="destructive", sources_allowed={"local", "remote"}),
    "take_screenshot": SkillPolicy(risk_level="reversible"),
    "organize_downloads": SkillPolicy(risk_level="destructive", sources_allowed={"local"}),
    "phone_call": SkillPolicy(risk_level="destructive", confirmation_required=True, sources_allowed={"local"}),
    "phone_send_sms": SkillPolicy(risk_level="external", confirmation_required=True, sources_allowed={"local"}),
    "phone_whatsapp": SkillPolicy(risk_level="external", confirmation_required=True, sources_allowed={"local"}),
    "run_routine": SkillPolicy(risk_level="reversible"),
}


def get_policy(name: str) -> SkillPolicy:
    """Return the policy for *name*, or a safe default."""
    return _DEFAULT_POLICIES.get(name, SkillPolicy(risk_level="reversible"))


def check(name: str, origin: str = "local") -> PolicyDecision:
    """Check whether *name* can run from *origin*.

    Returns a PolicyDecision with:
        allowed           – can the tool run at all from this origin?
        needs_confirmation – must the user confirm first?
        reason            – human-readable explanation if blocked.
    """
    policy = get_policy(name)

    # Source restriction
    if origin not in policy.sources_allowed:
        return PolicyDecision(
            allowed=False,
            reason=f"'{name}' is not allowed from {origin} requests.",
        )

    return PolicyDecision(
        allowed=True,
        needs_confirmation=policy.confirmation_required,
    )


def all_policies() -> dict[str, SkillPolicy]:
    """Return a copy of the full policy registry."""
    return dict(_DEFAULT_POLICIES)
