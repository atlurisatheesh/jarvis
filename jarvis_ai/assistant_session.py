"""Conversation/session state for Leha voice entry points."""
import time
from dataclasses import dataclass
from typing import Callable

from . import config
from .assistant_core import handle_local_intent, set_last_reply
from .wake_phrases import (
    INDIC_WAKE_TRIGGERS,
    OBSERVED_STRICT_WAKE_TRIGGERS,
    has_trigger,
    is_hallucination,
    normalize_text,
    strip_trigger,
)


_CLEAN_BARE_WAKE = {
    "leha", "leah", "leeha", "liha", "lleha",
    "hey leha", "hi leha", "hello leha", "ok leha", "okay leha",
    "hey leah", "hi leah", "hello leah", "ok leah", "okay leah",
    *OBSERVED_STRICT_WAKE_TRIGGERS,
    *INDIC_WAKE_TRIGGERS,
}


def _is_safe_wake_free_question(low: str) -> bool:
    """Read-only status/capability questions that are safe without a wake hit."""
    if not low:
        return False
    capability_words = {"access", "accessible", "capability", "capabilities"}
    if (set(low.split()) & capability_words) and any(
        word in low for word in ("laptop", "computer", "system", "you")
    ):
        return True
    return low in {
        "what can you do",
        "what all can you do",
        "what do you have access to",
        "what can you access",
        "what all can you access",
        "what access do you have",
    }


@dataclass
class TurnResult:
    heard: str
    reply: str = ""
    acted: bool = False
    quit_requested: bool = False
    ignored_reason: str = ""


class AssistantSession:
    """Alexa/Siri-style session gate: wake word -> follow-up window -> action."""

    def __init__(self, followup_seconds: int | None = None):
        self._explicit_followup_seconds = followup_seconds is not None
        self.followup_seconds = (
            config.FOLLOWUP_SECONDS if followup_seconds is None else followup_seconds
        )
        self.active_until = 0.0
        # Count of consecutive commands inside the current follow-up window.
        # Capped by CONVERSATION_MAX_TURNS so a stale session cannot be
        # extended indefinitely by background room audio.
        self._turn_count = 0
        self._last_command = ""
        self._last_command_time = 0.0

    def is_active(self) -> bool:
        return time.time() < self.active_until

    def activate(self, seconds: int | float | None = None, reset: bool = False):
        """Start/refresh the follow-up window after a turn."""
        if reset:
            self._turn_count = 0
        window = self.followup_seconds if seconds is None else seconds
        self.active_until = time.time() + max(0.0, float(window))
        self._turn_count += 1

    def deactivate(self):
        self.active_until = 0.0
        self._turn_count = 0

    def _is_replayed_command(self, command: str, seconds: int = 120) -> bool:
        """Block exact repeated commands caused by speaker echo or stale STT."""
        now = time.time()
        low = normalize_text(command)
        if low and low == self._last_command and now - self._last_command_time < seconds:
            return True
        self._last_command = low
        self._last_command_time = now
        return False

    def _at_turn_cap(self) -> bool:
        """True if the conversation must re-wake (safety cap reached)."""
        cap = getattr(config, "CONVERSATION_MAX_TURNS", 0) or 0
        return cap > 0 and self._turn_count >= cap

    def _is_clean_bare_wake(self, heard: str) -> bool:
        """Only clean wake transcripts may open a no-command follow-up window.

        Fuzzy one-word variants are useful when followed by a real command, but
        they cause false "Yes, Sir?" replies when room noise is transcribed as
        Leha-like text. Bare wake is therefore intentionally stricter.
        """
        return normalize_text(heard).strip(" ,.") in _CLEAN_BARE_WAKE

    def handle(self, heard: str, ask_brain: Callable[[str], str]) -> TurnResult:
        heard = (heard or "").strip()
        if not heard:
            return TurnResult(heard, ignored_reason="empty")

        low = normalize_text(heard)

        # Never run general local intents before the wake/session gate. Earlier
        # versions let unrelated room audio trigger calculators, screen tools,
        # and replies. Only explicit media stop/pause remains wake-free.
        wake_free_media = {
            "stop", "pause", "stop music", "pause music",
            "stop youtube", "pause youtube",
            "close youtube tab", "close youtube tabs",
            "close the youtube tab", "close the youtube tabs",
            "close you tube tab", "close the you tube tab",
            "close current tab", "close the current tab",
        }
        if config.WAKE_FREE_MEDIA_CONTROLS and low in wake_free_media:
            local = handle_local_intent(low, wake_free=True)
            if local.handled:
                if local.reply:
                    set_last_reply(local.reply)
                return TurnResult(heard, local.reply, True, local.quit_requested)

        if getattr(config, "WAKE_FREE_STATUS_QUESTIONS", False) and _is_safe_wake_free_question(low):
            local = handle_local_intent(low)
            if local.handled:
                if local.reply:
                    set_last_reply(local.reply)
                return TurnResult(heard, local.reply, True, local.quit_requested)

        triggered = has_trigger(heard)
        active = self.is_active() and not self._at_turn_cap()
        if config.REQUIRE_TRIGGER and not active and not triggered:
            return TurnResult(heard, ignored_reason="no wake trigger")

        if is_hallucination(heard):
            return TurnResult(heard, ignored_reason="hallucination")

        command = strip_trigger(heard) if triggered else low
        if self._is_replayed_command(command):
            return TurnResult(heard, ignored_reason="replayed_command")

        # Bare wake word, like "Leha" -> short acknowledgement.
        if triggered and len(command) < 2:
            if not self._is_clean_bare_wake(heard):
                return TurnResult(heard, ignored_reason="weak_bare_wake")
            self.activate(getattr(config, "WAKE_ONLY_FOLLOWUP_SECONDS", 20), reset=True)
            reply = "Yes, Sir?"
            set_last_reply(reply)
            return TurnResult(heard, reply, True)

        if triggered:
            self.activate(reset=True)

        local = handle_local_intent(command)
        if local.handled:
            if local.keep_active:
                self.activate()
            else:
                self.deactivate()
            if local.reply:
                set_last_reply(local.reply)
            return TurnResult(heard, local.reply, True, local.quit_requested)

        followup_brain_enabled = getattr(config, "FOLLOWUP_BRAIN_ENABLED", False)
        if self._explicit_followup_seconds and self.followup_seconds == 0:
            followup_brain_enabled = False
        if active and not triggered and not followup_brain_enabled:
            return TurnResult(heard, ignored_reason="followup_requires_wake")

        reply = ask_brain(command or heard)
        self.activate()
        set_last_reply(reply)
        return TurnResult(heard, reply, True)
