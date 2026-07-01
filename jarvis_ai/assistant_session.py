"""Conversation/session state for Leha voice entry points."""
import time
from dataclasses import dataclass
from typing import Callable

from . import config
from .assistant_core import handle_local_intent, set_last_reply
from .wake_phrases import has_trigger, is_hallucination, normalize_text, strip_trigger


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
        self.followup_seconds = (
            config.FOLLOWUP_SECONDS if followup_seconds is None else followup_seconds
        )
        self.active_until = 0.0
        # Count of consecutive commands inside the current follow-up window.
        # Capped by CONVERSATION_MAX_TURNS so a stale session cannot be
        # extended indefinitely by background room audio.
        self._turn_count = 0

    def is_active(self) -> bool:
        return time.time() < self.active_until

    def activate(self):
        """Start/refresh the follow-up window after a turn."""
        self.active_until = time.time() + self.followup_seconds
        self._turn_count += 1

    def deactivate(self):
        self.active_until = 0.0
        self._turn_count = 0

    def _at_turn_cap(self) -> bool:
        """True if the conversation must re-wake (safety cap reached)."""
        cap = getattr(config, "CONVERSATION_MAX_TURNS", 0) or 0
        return cap > 0 and self._turn_count >= cap

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
        }
        if config.WAKE_FREE_MEDIA_CONTROLS and low in wake_free_media:
            local = handle_local_intent(low, wake_free=True)
            if local.handled:
                if local.reply:
                    set_last_reply(local.reply)
                return TurnResult(heard, local.reply, True, local.quit_requested)

        triggered = has_trigger(heard)
        active = self.is_active() and not self._at_turn_cap()
        if config.REQUIRE_TRIGGER and not active and not triggered:
            return TurnResult(heard, ignored_reason="no wake trigger")

        if is_hallucination(heard) and not (triggered or active):
            return TurnResult(heard, ignored_reason="hallucination")

        command = strip_trigger(heard) if triggered else low

        if triggered:
            self.activate()

        # Bare wake word, like "Leha" -> short acknowledgement.
        if triggered and len(command) < 2:
            reply = "Yes, Sir?" if config.SPEAK_WAKE_ACK else ""
            set_last_reply(reply)
            return TurnResult(heard, reply, True)

        local = handle_local_intent(command)
        if local.handled:
            if local.keep_active:
                self.activate()
            else:
                self.deactivate()
            if local.reply:
                set_last_reply(local.reply)
            return TurnResult(heard, local.reply, True, local.quit_requested)

        reply = ask_brain(command or heard)
        self.activate()
        set_last_reply(reply)
        return TurnResult(heard, reply, True)
