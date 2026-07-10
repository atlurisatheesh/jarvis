"""Phase A tests: hands-free conversation flow + self-protecting barge-in."""
import time
import unittest
from unittest.mock import patch

from jarvis_ai.assistant_session import AssistantSession, TurnResult
from jarvis_ai.barge_in_guard import BargeInGuard


# ---------------------------------------------------------------------------
# Follow-up window (continuous conversation)
# ---------------------------------------------------------------------------

class TestFollowUpWindow(unittest.TestCase):
    def setUp(self):
        # Patch config so tests are deterministic regardless of config.py.
        self._cfg = patch("jarvis_ai.config.FOLLOWUP_SECONDS", 15)
        self._cfg.start()
        self.addCleanup(self._cfg.stop)
        self._cap = patch("jarvis_ai.config.CONVERSATION_MAX_TURNS", 6)
        self._cap.start()
        self.addCleanup(self._cap.stop)

    def test_session_starts_inactive(self):
        s = AssistantSession()
        self.assertFalse(s.is_active())

    def test_activate_opens_window(self):
        s = AssistantSession()
        s.activate()
        self.assertTrue(s.is_active())

    def test_window_expires(self):
        s = AssistantSession(followup_seconds=0)
        s.activate()
        # followup_seconds=0 -> window is already in the past after activate
        time.sleep(0.01)
        self.assertFalse(s.is_active())

    def test_activate_refreshes_window(self):
        s = AssistantSession()
        s.activate()
        first = s.active_until
        time.sleep(0.01)
        s.activate()
        self.assertGreater(s.active_until, first)

    def test_turn_cap_forces_rewake(self):
        s = AssistantSession()
        for _ in range(6):
            s.activate()
        # After 6 turns, is_active must account for the cap.
        self.assertTrue(s._at_turn_cap())

    def test_deactivate_resets_turn_count(self):
        s = AssistantSession()
        for _ in range(5):
            s.activate()
        s.deactivate()
        self.assertEqual(s._turn_count, 0)
        self.assertFalse(s._at_turn_cap())

    def test_session_gate_requires_trigger_when_inactive(self):
        """Without an active session and no wake word, command is ignored."""
        s = AssistantSession()
        with patch("jarvis_ai.config.REQUIRE_TRIGGER", True), \
             patch("jarvis_ai.config.WAKE_FREE_MEDIA_CONTROLS", True):
            result = s.handle("set a timer for ten minutes", lambda _: "should not run")
        self.assertEqual(result.ignored_reason, "no wake trigger")
        self.assertFalse(result.acted)

    def test_followup_command_runs_without_trigger(self):
        """Inside the follow-up window, a command runs without re-waking."""
        s = AssistantSession(followup_seconds=25)
        s.activate()  # open the window
        with patch("jarvis_ai.config.REQUIRE_TRIGGER", True), \
             patch("jarvis_ai.config.WAKE_FREE_MEDIA_CONTROLS", True):
            result = s.handle("what is the weather", lambda t: f"raining, sir")
        self.assertTrue(result.acted)
        self.assertEqual(result.reply, "raining, sir")

    def test_turn_cap_blocks_followup(self):
        """Once the turn cap is hit, even an active-timestamp requires a re-wake."""
        s = AssistantSession()
        for _ in range(6):
            s.activate()
        # active_until is in the future, but the cap should block it.
        self.assertTrue(s.active_until > time.time())
        with patch("jarvis_ai.config.REQUIRE_TRIGGER", True), \
             patch("jarvis_ai.config.WAKE_FREE_MEDIA_CONTROLS", True):
            result = s.handle("another command", lambda _: "reply")
        self.assertEqual(result.ignored_reason, "no wake trigger")


# ---------------------------------------------------------------------------
# Barge-in echo self-trigger detection
# ---------------------------------------------------------------------------

class TestBargeInGuard(unittest.TestCase):
    def setUp(self):
        self._echo_flag = patch("jarvis_ai.config.AUTO_DISABLE_BARGE_IN_ON_ECHO", True)
        self._echo_flag.start()
        self.addCleanup(self._echo_flag.stop)
        self._limit = patch("jarvis_ai.config.BARGE_IN_ECHO_LIMIT", 2)
        self._limit.start()
        self.addCleanup(self._limit.stop)
        self._window = patch("jarvis_ai.config.BARGE_IN_ECHO_WINDOW_S", 60.0)
        self._window.start()
        self.addCleanup(self._window.stop)

    def test_short_command_not_echo(self):
        """A genuine 'stop' interrupt is never classified as echo."""
        g = BargeInGuard()
        g.record_spoken("The weather today is sunny with a high of 32 degrees sir")
        self.assertFalse(g.classify_interrupt("stop"))
        self.assertFalse(g.classify_interrupt("leha stop"))
        self.assertFalse(g.classify_interrupt("pause"))

    def test_echo_of_recent_speech_detected(self):
        """An interrupt that matches recent spoken text is flagged as echo."""
        g = BargeInGuard()
        g.record_spoken("the weather today is sunny with a high of 32 degrees sir")
        self.assertTrue(
            g.classify_interrupt("the weather today is sunny with a high of 32 degrees")
        )

    def test_unrelated_text_not_echo(self):
        g = BargeInGuard()
        g.record_spoken("the weather today is sunny with a high of 32 degrees sir")
        self.assertFalse(g.classify_interrupt("turn off the kitchen lights please"))

    def test_genuine_interrupt_clears_false_count(self):
        g = BargeInGuard()
        g.record_spoken("the weather today is sunny with a high of 32 degrees sir")
        # First echo (counts as 1)
        g.register_interrupt("the weather today is sunny with a high of 32 degrees")
        self.assertFalse(g.disabled)
        # Genuine interrupt clears the count
        g.register_interrupt("stop")
        self.assertFalse(g.disabled)
        # Echo again — should be count 1, not disabled yet
        disabled = g.register_interrupt("the weather today is sunny with a high of 32 degrees")
        self.assertFalse(disabled)

    def test_disables_after_limit(self):
        g = BargeInGuard()
        g.record_spoken("the weather today is sunny with a high of 32 degrees sir")
        # First echo
        disabled1 = g.register_interrupt("the weather today is sunny with a high of 32 degrees")
        self.assertFalse(disabled1)
        self.assertFalse(g.disabled)
        # Second echo -> trips the limit (default 2)
        disabled2 = g.register_interrupt("the weather today is sunny with a high of 32 degrees")
        self.assertTrue(disabled2)
        self.assertTrue(g.disabled)
        # Further interrupts are ignored once disabled.
        self.assertFalse(g.register_interrupt("the weather today is sunny with a high"))

    def test_window_expiry(self):
        g = BargeInGuard()
        with patch("jarvis_ai.config.BARGE_IN_ECHO_WINDOW_S", 0.05):
            g.record_spoken("the weather today is sunny with a high of 32 degrees sir")
            g.register_interrupt("the weather today is sunny with a high of 32 degrees")
            time.sleep(0.08)
            # After the window, old echo no longer counts toward the limit.
            disabled = g.register_interrupt("the weather today is sunny with a high of 32 degrees")
        self.assertFalse(disabled)

    def test_reset(self):
        g = BargeInGuard()
        g.record_spoken("the weather today is sunny with a high of 32 degrees sir")
        g.register_interrupt("the weather today is sunny with a high of 32 degrees")
        g.reset()
        self.assertFalse(g.disabled)
        self.assertEqual(len(g._false_interrupts), 0)

    def test_can_be_disabled_via_config(self):
        """When AUTO_DISABLE_BARGE_IN_ON_ECHO is False, never disable."""
        with patch("jarvis_ai.config.AUTO_DISABLE_BARGE_IN_ON_ECHO", False):
            g = BargeInGuard()
            g.record_spoken("the weather today is sunny with a high of 32 degrees sir")
            for _ in range(5):
                g.register_interrupt("the weather today is sunny with a high of 32 degrees")
            self.assertFalse(g.disabled)


if __name__ == "__main__":
    unittest.main(verbosity=2)
