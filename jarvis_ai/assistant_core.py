"""Fast local intent routing for assistant-like reflexes.

Siri/Alexa-style assistants do not send every short command to the language
model. Playback, volume, wake/session, and common launch commands should happen
locally and immediately.
"""
import re
import time
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import quote_plus

from . import skills
from . import speaker_profile
from .wake_phrases import normalize_text


@dataclass
class IntentResult:
    handled: bool
    reply: str = ""
    keep_active: bool = True
    quit_requested: bool = False
    action: str = ""


QUIT_COMMANDS = {"exit", "quit", "goodbye", "stop listening", "shutdown leha"}

STOP_WORDS = {"stop", "pause", "halt", "shut"}
RESUME_WORDS = {"resume", "continue"}
NEXT_WORDS = {"next", "skip"}
PREV_WORDS = {"previous", "prev", "back"}
MEDIA_CONTEXT = {"music", "song", "songs", "youtube", "video", "playback", "audio", "media"}

MUSIC_WORDS = {
    "youtube", "you tube", "music", "musing", "amusing", "song", "songs",
    "video", "telugu", "tamil", "hindi", "ilayaraja", "ilaiyaraaja",
    "ilayaraj", "raja", "playlist", "movie",
}

APP_ALIASES = {
    "youtube": "https://www.youtube.com",
    "you tube": "https://www.youtube.com",
    "google": "https://www.google.com",
    "gmail": "https://mail.google.com",
    "chrome": "chrome",
    "notepad": "notepad",
    "calculator": "calc",
    "calc": "calc",
    "whatsapp": "whatsapp:",
    "spotify": "spotify",
}

PHONE_APP_ALIASES = {
    "whatsapp": "com.whatsapp",
    "chrome": "com.android.chrome",
    "youtube": "com.google.android.youtube",
    "gmail": "com.google.android.gm",
    "spotify": "com.spotify.music",
    "maps": "com.google.android.apps.maps",
    "google maps": "com.google.android.apps.maps",
}

CLOSE_APP_ALIASES = {
    "chrome": "chrome",
    "google chrome": "chrome",
    "edge": "edge",
    "browser": "chrome",
    "youtube": "youtube",
    "you tube": "youtube",
    "notepad": "notepad",
    "calculator": "calculator",
    "calc": "calculator",
    "spotify": "spotify",
}

# --- shared context with the voice loop ---
_media_state = {"active": False, "last_action": "", "last_action_time": 0.0}
_last_reply = {"text": ""}

# Safety confirmation for destructive actions
_PENDING_CONFIRM = {"action": None, "callback": None, "prompt": ""}


def _require_confirm(action: str, callback, prompt: str) -> IntentResult:
    """Set a pending confirmation and ask the user to confirm."""
    _PENDING_CONFIRM["action"] = action
    _PENDING_CONFIRM["callback"] = callback
    _PENDING_CONFIRM["prompt"] = prompt
    return IntentResult(True, prompt, keep_active=True, action=f"confirm_{action}")


def _clear_pending():
    _PENDING_CONFIRM["action"] = None
    _PENDING_CONFIRM["callback"] = None
    _PENDING_CONFIRM["prompt"] = ""


def set_media_active(action: str):
    _media_state["active"] = True
    _media_state["last_action"] = action
    _media_state["last_action_time"] = time.time()


def clear_media_active():
    _media_state["active"] = False


def set_last_reply(text: str):
    _last_reply["text"] = text


def media_recent(seconds: int = 900) -> bool:
    return _media_state["active"] and time.time() - _media_state["last_action_time"] < seconds


def _words(text: str) -> set[str]:
    return set(normalize_text(text).split())


def _is_media_stop(text: str) -> bool:
    low = normalize_text(text)
    if low in {"stop", "pause", "stop music", "pause music", "stop youtube", "pause youtube"}:
        return True
    words = _words(low)
    # "shut" is only a media command when media is explicit/recent. Without
    # this guard, "shut down laptop" can be mistaken for a pause request.
    safe_stop_words = {"stop", "pause", "halt"}
    if words & safe_stop_words and (words & MEDIA_CONTEXT or len(words) <= 3):
        return True
    if "shut" in words and (words & MEDIA_CONTEXT or media_recent()):
        return True
    # context-aware: if we recently played media, plain "stop" counts
    if words & STOP_WORDS and len(words) <= 3:
        if media_recent():
            return True
    return False


def _is_media_resume(text: str) -> bool:
    words = _words(text)
    return bool(words & RESUME_WORDS and (words & MEDIA_CONTEXT or len(words) <= 3 or media_recent()))


def _is_media_next(text: str) -> bool:
    words = _words(text)
    return bool(words & NEXT_WORDS and (words & MEDIA_CONTEXT or len(words) <= 3 or media_recent()))


def _is_media_prev(text: str) -> bool:
    words = _words(text)
    return bool(words & PREV_WORDS and (words & MEDIA_CONTEXT or len(words) <= 3 or media_recent()))


def _volume_match(text: str) -> re.Match | None:
    return re.search(r"\b(?:volume|sound)\s+(up|down)\b", normalize_text(text))


def _cleanup_youtube_query(text: str) -> str:
    low = normalize_text(text)
    query = re.split(r"\b(?:play|olay|playe|start)\b", low, maxsplit=1)[-1].strip()
    query = re.sub(r"\b(in|on|from)\s+(youtube|you tube)\b", "", query).strip()
    query = query.replace("amusing", "music").replace("musing", "music")
    query = re.sub(r"\btelug\b", "telugu", query)
    query = " ".join(query.split())
    if not query or query in {"youtube", "you tube"}:
        query = "music"
    return query


def _is_youtube_play(text: str) -> bool:
    low = normalize_text(text)
    if not re.search(r"\b(play|olay|playe|start)\b", low):
        return False
    return any(word in low for word in MUSIC_WORDS)


def _is_spotify_play(text: str) -> bool:
    low = normalize_text(text)
    return "spotify" in low and re.search(r"\b(play|olay|playe|start)\b", low) is not None


def _cleanup_spotify_query(text: str) -> str:
    low = normalize_text(text)
    query = re.split(r"\b(?:play|olay|playe|start)\b", low, maxsplit=1)[-1].strip()
    query = re.sub(r"\b(in|on|from)\s+spotify\b", "", query).strip()
    query = re.sub(r"\bspotify\b", "", query).strip()
    query = " ".join(query.split())
    return query or "music"


def _morning_brief() -> str:
    parts = [f"It is {datetime.now():%I:%M %p on %A}."]
    for tool in ("get_weather", "list_reminders", "system_info"):
        result = skills.run_tool(tool, {})
        if result:
            parts.append(result)
    return " ".join(parts)


def _open_target(text: str) -> IntentResult | None:
    low = normalize_text(text)
    match = re.match(r"^(open|launch|start)\s+(.+)$", low)
    if not match:
        return None
    target = match.group(2).strip()
    target = re.sub(r"\b(app|application|website|site)\b", "", target).strip()
    if not target:
        return None

    mapped = APP_ALIASES.get(target, target)
    if mapped.startswith(("http://", "https://")):
        result = skills.run_tool("open_url", {"url": mapped})
    else:
        result = skills.run_tool("open_app", {"name": mapped})
    return IntentResult(True, result, action="open")


def _close_target(text: str) -> IntentResult | None:
    low = normalize_text(text)
    if low in {"close", "close this", "close it", "close anything", "close window", "close current window"}:
        result = skills.run_tool("close_current_window", {})
        return IntentResult(True, result, action="close_window")

    if low in {"close tab", "close this tab", "close current tab", "close youtube tab", "close youtube tabs", "close browser tab"}:
        result = skills.run_tool("close_current_tab", {"count": 1})
        return IntentResult(True, result, action="close_tab")

    match = re.match(r"^(close|quit|exit)\s+(.+)$", low)
    if not match:
        return None
    target = match.group(2).strip()
    target = re.sub(r"\b(app|application|window|website|site)\b", "", target).strip()
    if target in {"tab", "tabs", "current tab", "this tab"}:
        result = skills.run_tool("close_current_tab", {"count": 1})
        return IntentResult(True, result, action="close_tab")
    mapped = CLOSE_APP_ALIASES.get(target)
    if mapped:
        if mapped in {"youtube"}:
            result = skills.run_tool("close_current_tab", {"count": 1})
            return IntentResult(True, "Closed the current YouTube tab.", action="close_tab")
        result = skills.run_tool("close_app", {"name": mapped})
        return IntentResult(True, result, action="close_app")
    result = skills.run_tool("close_current_window", {})
    return IntentResult(True, result, action="close_window")


def _parse_timer(text: str) -> tuple[int, str] | None:
    low = normalize_text(text)
    m = re.search(r"\b(\d+)\s*minute", low)
    if not m:
        m = re.search(r"timer\s+(\d+)\s*minute", low)
    if m:
        minutes = int(m.group(1))
        label = "timer"
        label_m = re.search(r"timer\s+(?:for\s+)?([a-z0-9 ]+?)\s+(?:for\s+)?\d+\s*minute", low)
        if label_m:
            label = label_m.group(1).strip()
        return minutes, label
    return None


def handle_local_intent(text: str, wake_free: bool = False) -> IntentResult:
    """Return a handled result for common local commands, otherwise unhandled."""
    low = normalize_text(text)
    if not low:
        return IntentResult(False)

    # ── Pending confirmation check ────────────────────────────────────
    if _PENDING_CONFIRM["action"]:
        if low in {"yes", "confirm", "yeah", "sure", "do it", "yes please", "yes sir"}:
            cb = _PENDING_CONFIRM["callback"]
            act = _PENDING_CONFIRM["action"]
            _clear_pending()
            result = cb()
            return IntentResult(True, result, keep_active=False, action=act)
        if low in {"no", "cancel", "nevermind", "abort", "stop", "forget it", "no thanks"}:
            _clear_pending()
            return IntentResult(True, "Cancelled, Sir.", keep_active=False, action="cancel")

    if low in QUIT_COMMANDS:
        return IntentResult(True, "Goodbye, Sir.", keep_active=False, quit_requested=True, action="quit")

    if low in {"cancel", "nevermind", "abort", "forget it", "ignore that"}:
        return IntentResult(True, "Cancelled, Sir.", keep_active=False, action="cancel")

    if low in {"thank you", "thanks", "thank you leha", "thanks leha", "okay", "ok", "got it"}:
        return IntentResult(True, "You're welcome, Sir.", keep_active=True, action="thanks")

    if low in {"repeat", "say that again", "what did you say", "pardon"}:
        reply = _last_reply["text"] or "I didn't say anything yet, Sir."
        return IntentResult(True, reply, keep_active=True, action="repeat")

    if low in {"voice profile", "voice status", "speaker profile", "owner voice status"}:
        state = "trained" if speaker_profile.has_profile() else "not trained"
        enabled = "enabled" if getattr(speaker_profile.config, "SPEAKER_VERIFY_ENABLED", False) else "disabled"
        return IntentResult(True, f"Voice profile is {state}; verification is {enabled}.", action="voice_status")

    if low in {"voice mode", "speech mode", "tts mode"}:
        from . import config
        mode = config.TTS_ENGINE
        clone_ready = "ready" if config.CLONE_TTS_REFERENCE else "not configured"
        return IntentResult(True, f"Voice mode is {mode}. Cloned voice is {clone_ready}.", action="voice_mode")

    if low in {"date", "what date", "what is the date", "today date", "what day", "what day is it"}:
        return IntentResult(True, datetime.now().strftime("Today is %A, %d %B %Y."), action="date")

    if _is_media_stop(low):
        result = skills.run_tool("media_play_pause", {})
        clear_media_active()
        print(f"[direct] media_play_pause() -> {result}", flush=True)
        return IntentResult(True, "Paused, Sir.", action="media_pause")

    if _is_media_resume(low):
        result = skills.run_tool("media_play_pause", {})
        set_media_active("media_resume")
        print(f"[direct] media_play_pause() -> {result}", flush=True)
        return IntentResult(True, "Playing, Sir.", action="media_resume")

    if _is_media_next(low):
        result = skills.run_tool("media_next", {})
        set_media_active("media_next")
        print(f"[direct] media_next() -> {result}", flush=True)
        return IntentResult(True, "Next, Sir.", action="media_next")

    if _is_media_prev(low):
        result = skills.run_tool("media_prev", {})
        set_media_active("media_prev")
        print(f"[direct] media_prev() -> {result}", flush=True)
        return IntentResult(True, "Previous, Sir.", action="media_previous")

    volume_match = _volume_match(low)
    if volume_match:
        result = skills.run_tool("set_volume", {"direction": volume_match.group(1), "steps": 5})
        print(f"[direct] set_volume({volume_match.group(1)!r}) -> {result}", flush=True)
        return IntentResult(True, result, action="volume")

    # Wake-free mode is intentionally narrow: only safe media controls above.
    if wake_free:
        return IntentResult(False)

    if low in {"brief me", "daily brief", "morning brief", "status brief", "what is my briefing"}:
        return IntentResult(True, _morning_brief(), action="brief")

    if low in {"battery", "battery status", "system status", "laptop status", "cpu status"}:
        result = skills.run_tool("system_info", {})
        return IntentResult(True, result, action="system_info")

    if low in {"weather", "weather today", "farm weather", "rain today", "rain forecast"}:
        result = skills.run_tool("get_weather", {})
        return IntentResult(True, result, action="weather")

    timer_info = _parse_timer(low)
    if timer_info:
        minutes, label = timer_info
        result = skills.run_tool("set_timer", {"minutes": minutes, "label": label})
        return IntentResult(True, result, action="timer")

    if low in {"list timers", "show timers", "timers"}:
        result = skills.run_tool("list_timers", {})
        return IntentResult(True, result, action="list_timers")

    if low in {"reminders", "list reminders", "show reminders", "pending reminders"}:
        result = skills.run_tool("list_reminders", {})
        return IntentResult(True, result, action="list_reminders")

    if _is_spotify_play(low):
        query = _cleanup_spotify_query(low)
        url = "https://open.spotify.com/search/" + quote_plus(query)
        result = skills.run_tool("open_url", {"url": url})
        set_media_active("spotify_play")
        return IntentResult(True, f"Opening Spotify for {query}.", action="spotify_play")

    if _is_youtube_play(low):
        query = _cleanup_youtube_query(low)
        result = skills.run_tool("play_youtube", {"query": query})
        set_media_active("youtube_play")
        print(f"[direct] play_youtube({query!r}) -> {result}", flush=True)
        return IntentResult(True, result, action="youtube_play")

    maps_match = re.match(r"^(?:navigate|directions?)\s+(?:to\s+)?(.+)$", low)
    if maps_match:
        result = skills.run_tool("open_google_maps", {"destination": maps_match.group(1).strip()})
        return IntentResult(True, result, action="google_maps")

    phone_open = re.match(r"^(?:open|launch|start)\s+(.+?)\s+(?:on|in)\s+(?:my\s+)?phone$", low)
    if phone_open:
        app_name = phone_open.group(1).strip()
        package = PHONE_APP_ALIASES.get(app_name)
        if package:
            result = skills.run_tool("phone_open_app", {"package": package})
            return IntentResult(True, result, action="phone_open_app")
        return IntentResult(True, f"I need the Android package name for {app_name}.", action="phone_unknown_app")

    opened = _open_target(low)
    if opened:
        return opened

    closed = _close_target(low)
    if closed:
        return closed

    if low in {"time", "what time", "what time is it", "tell time", "tell me time"}:
        result = skills.run_tool("tell_time", {})
        return IntentResult(True, result, action="time")

    # ── Windows system control reflexes ───────────────────────────────

    # Power commands — require confirmation
    if re.search(r"\b(sleep|suspend|hibernate(?! laptop))\b", low) and re.search(r"\b(computer|laptop|pc|system)\b", low) or low in {"sleep", "suspend", "go to sleep"}:
        return _require_confirm(
            "sleep_pc",
            lambda: skills.run_tool("sleep_pc", {}),
            "Sleep the laptop, Sir? Say yes or no.",
        )

    if re.search(r"\b(shutdown|shut down|power off|turn off|switch off)\b", low) and re.search(r"\b(computer|laptop|pc|system)\b", low):
        return _require_confirm(
            "shutdown_pc",
            lambda: skills.run_tool("shutdown_pc", {}),
            "Shut down the laptop, Sir? Say yes or no.",
        )

    if re.search(r"\b(restart|reboot|re-boot)\b", low) and re.search(r"\b(computer|laptop|pc|system)\b", low):
        return _require_confirm(
            "restart_pc",
            lambda: skills.run_tool("restart_pc", {}),
            "Restart the laptop, Sir? Say yes or no.",
        )

    if re.search(r"\b(hibernate)\b", low):
        return _require_confirm(
            "hibernate_pc",
            lambda: skills.run_tool("hibernate_pc", {}),
            "Hibernate the laptop, Sir? Say yes or no.",
        )

    # Screen / display
    if low in {"turn off screen", "turn off monitor", "screen off", "monitor off", "blank screen"}:
        result = skills.run_tool("turn_off_screen", {})
        return IntentResult(True, result, action="turn_off_screen")

    m_bright = re.match(r"(?:set\s+)?brightness\s+(?:to\s+)?(\d{1,3})\s*(?:percent|%)?$", low)
    if m_bright:
        result = skills.run_tool("set_brightness", {"percent": int(m_bright.group(1))})
        return IntentResult(True, result, action="brightness")

    if low in {"brightness up", "increase brightness"}:
        result = skills.run_tool("set_brightness", {"percent": 80})
        return IntentResult(True, result, action="brightness")

    if low in {"brightness down", "decrease brightness", "dim screen", "dim"}:
        result = skills.run_tool("set_brightness", {"percent": 30})
        return IntentResult(True, result, action="brightness")

    # Theme
    if low in {"dark mode", "enable dark mode", "switch to dark mode", "dark theme"}:
        result = skills.run_tool("dark_mode", {"enable": True})
        return IntentResult(True, result, action="dark_mode")

    if low in {"light mode", "enable light mode", "switch to light mode", "light theme"}:
        result = skills.run_tool("dark_mode", {"enable": False})
        return IntentResult(True, result, action="light_mode")

    # Desktop / windows
    if low in {"show desktop", "minimize everything", "minimize all windows"}:
        result = skills.run_tool("show_desktop", {})
        return IntentResult(True, result, action="show_desktop")

    if low in {"minimize all", "minimize all apps"}:
        result = skills.run_tool("minimize_all", {})
        return IntentResult(True, result, action="minimize_all")

    # Network
    if low in {"wifi on", "turn on wifi", "enable wifi", "wifi enable"}:
        result = skills.run_tool("toggle_wifi", {"state": "on"})
        return IntentResult(True, result, action="wifi_on")

    if low in {"wifi off", "turn off wifi", "disable wifi", "wifi disable"}:
        result = skills.run_tool("toggle_wifi", {"state": "off"})
        return IntentResult(True, result, action="wifi_off")

    if low in {"my ip", "what is my ip", "ip address", "what is my ip address"}:
        result = skills.run_tool("get_ip", {})
        return IntentResult(True, result, action="get_ip")

    if low in {"wifi networks", "list wifi", "show wifi networks", "available networks"}:
        result = skills.run_tool("list_wifi", {})
        return IntentResult(True, result, action="list_wifi")

    # Processes
    if low in {"top processes", "what is using cpu", "cpu usage", "show processes",
                "list processes", "running processes"}:
        result = skills.run_tool("get_processes", {"count": 5})
        return IntentResult(True, result, action="get_processes")

    m_kill = re.match(r"(?:kill|force close|force quit|end)\s+(?:process\s+)?(.+)$", low)
    if m_kill:
        proc = m_kill.group(1).strip()
        result = skills.run_tool("kill_process", {"name": proc})
        return IntentResult(True, result, action="kill_process")

    # Battery
    if low in {"battery report", "battery health", "show battery report"}:
        result = skills.run_tool("battery_report", {})
        return IntentResult(True, result, action="battery_report")

    # ── Screen awareness + personal context ───────────────────────────
    if low in {"read screen", "read the screen", "read my screen", "what does the screen say"}:
        result = skills.run_tool("read_screen", {})
        return IntentResult(True, result, action="read_screen")

    if low in {"what is on screen", "what is on the screen", "what is on my screen",
                "describe screen", "describe the screen", "look at screen", "look at the screen",
                "what am i looking at", "see screen", "see the screen"}:
        result = skills.run_tool("see_screen", {"question": "What is on the screen?"})
        return IntentResult(True, result, action="see_screen")

    if low in {"read clipboard", "what is in clipboard", "what is on my clipboard",
                "read my clipboard", "clipboard"}:
        result = skills.run_tool("read_clipboard", {})
        return IntentResult(True, result, action="read_clipboard")

    if low in {"recent files", "what did i change", "recently changed files",
                "what changed today", "recent changes"}:
        result = skills.run_tool("recent_files", {"hours": 24})
        return IntentResult(True, result, action="recent_files")

    # Email
    if low in {"check email", "check my email", "any new email", "any new mail",
                "unread email", "unread mail", "new email", "do i have email",
                "do i have any email", "check mail"}:
        result = skills.run_tool("unread_email", {})
        return IntentResult(True, result, action="unread_email")

    if low in {"recent email", "latest email", "recent mail", "latest mail",
                "show my email", "read my email"}:
        result = skills.run_tool("recent_email", {"count": 5})
        return IntentResult(True, result, action="recent_email")

    # Phone SMS
    if low in {"read my messages", "read messages", "any new messages",
                "any new texts", "check messages", "check my messages",
                "any text messages", "read my texts", "read texts"}:
        result = skills.run_tool("phone_unread_sms", {})
        return IntentResult(True, result, action="phone_unread_sms")

    if low in {"recent messages", "recent texts", "latest messages", "show messages",
                "show my messages", "latest texts"}:
        result = skills.run_tool("phone_read_sms", {"count": 5})
        return IntentResult(True, result, action="phone_read_sms")

    # Android phone controls. These stay behind the normal wake/session gate;
    # only the playback controls above are allowed wake-free.
    if low in {"phone status", "my phone status", "is my phone connected",
               "check my phone", "check phone connection"}:
        result = skills.run_tool("phone_status", {})
        return IntentResult(True, result, action="phone_status")

    if low in {"phone notifications", "read phone notifications", "check phone notifications",
               "what are my phone notifications"}:
        result = skills.run_tool("phone_notifications", {})
        return IntentResult(True, result, action="phone_notifications")

    if low in {"phone screenshot", "take phone screenshot", "screenshot my phone",
               "show my phone screen"}:
        result = skills.run_tool("phone_screenshot", {})
        return IntentResult(True, result, action="phone_screenshot")

    if low in {"find my phone", "ring my phone", "where is my phone"}:
        result = skills.run_tool("phone_ring", {})
        return IntentResult(True, result, action="phone_ring")

    if low in {"phone home", "go home on phone"}:
        result = skills.run_tool("phone_key", {"key": "home"})
        return IntentResult(True, result, action="phone_home")

    if low in {"phone back", "go back on phone"}:
        result = skills.run_tool("phone_key", {"key": "back"})
        return IntentResult(True, result, action="phone_back")

    return IntentResult(False)
