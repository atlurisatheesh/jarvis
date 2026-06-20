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

    def is_active(self) -> bool:
        return time.time() < self.active_until

    def activate(self):
        self.active_until = time.time() + self.followup_seconds

    def deactivate(self):
        self.active_until = 0.0

    def handle(self, heard: str, ask_brain: Callable[[str], str]) -> TurnResult:
        heard = (heard or "").strip()
        if not heard:
            return TurnResult(heard, ignored_reason="empty")

        low = normalize_text(heard)

        # Always allow a very small safe command set before hallucination checks.
        # Short words like "stop" are valid commands and also look like STT noise.
        local = handle_local_intent(low, wake_free=config.WAKE_FREE_MEDIA_CONTROLS)
        if local.handled:
            if local.keep_active:
                self.activate()
            else:
                self.deactivate()
            if local.reply:
                set_last_reply(local.reply)
            return TurnResult(heard, local.reply, True, local.quit_requested)

        if is_hallucination(heard):
            return TurnResult(heard, ignored_reason="hallucination")

        triggered = has_trigger(heard)
        active = self.is_active()
        if config.REQUIRE_TRIGGER and not active and not triggered:
            return TurnResult(heard, ignored_reason="no wake trigger")

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
