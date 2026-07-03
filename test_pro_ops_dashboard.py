"""Pro operations tests: dashboard, proactive policy, and voice reflexes."""
from __future__ import annotations

from datetime import datetime
import unittest
from unittest.mock import patch


class TestProOpsDashboard(unittest.TestCase):
    def test_dashboard_status_contains_core_sections(self):
        from jarvis_ai import pro_ops
        status = pro_ops.dashboard_status()
        for key in ("health", "runtime", "latency", "voice", "barge_in",
                    "wake_validation", "notifications", "audit", "gaps"):
            self.assertIn(key, status)

    def test_spoken_status_is_short(self):
        from jarvis_ai import pro_ops
        text = pro_ops.spoken_status()
        self.assertIn("Pro mode:", text)
        self.assertLess(len(text), 220)

    def test_barge_in_recommends_off_without_aec(self):
        from jarvis_ai import pro_ops
        with patch("jarvis_ai.config.AEC_ENABLED", False), \
             patch("jarvis_ai.config.AEC_HARDWARE_DEVICE", None), \
             patch("jarvis_ai.config.BARGE_IN_ENABLED", False):
            status = pro_ops.barge_in_status()
        self.assertFalse(status["safe_to_enable"])
        self.assertIn("Keep barge-in off", status["recommendation"])


class TestProactiveNotificationPolicy(unittest.TestCase):
    def tearDown(self):
        from jarvis_ai import notifier
        notifier.clear()

    def test_quiet_hours_blocks_non_important_speech(self):
        from jarvis_ai import notifier
        with patch("jarvis_ai.config.PROACTIVE_QUIET_HOURS_START", "22:00"), \
             patch("jarvis_ai.config.PROACTIVE_QUIET_HOURS_END", "07:00"), \
             patch("jarvis_ai.notifier.datetime") as dt:
            dt.now.return_value = datetime(2026, 1, 1, 23, 30)
            self.assertFalse(notifier.should_speak("reminder"))
            self.assertTrue(notifier.should_speak("reminder", important=True))

    def test_speak_only_useful_blocks_generic_source(self):
        from jarvis_ai import notifier
        with patch("jarvis_ai.config.PROACTIVE_SPEAK_ONLY_USEFUL", True), \
             patch("jarvis_ai.notifier._in_quiet_hours", return_value=False), \
             patch("jarvis_ai.notifier._spoken_limit_reached", return_value=False):
            self.assertFalse(notifier.should_speak("system"))
            self.assertTrue(notifier.should_speak("reminder"))

    def test_notify_queues_but_does_not_speak_when_policy_blocks(self):
        from jarvis_ai import notifier

        class Speaker:
            spoken = []

            def say(self, text):
                self.spoken.append(text)

        speaker = Speaker()
        notifier.register_speaker(speaker)
        with patch("jarvis_ai.notifier.should_speak", return_value=False):
            self.assertTrue(notifier.notify("Low value", source="system", speak=True))
        self.assertEqual(speaker.spoken, [])
        self.assertIn("Low value", notifier.pending_summary())


class TestProVoiceReflexes(unittest.TestCase):
    def test_pro_status_reflex_does_not_call_brain(self):
        from jarvis_ai.assistant_session import AssistantSession
        with patch("jarvis_ai.pro_ops.spoken_status", return_value="Pro mode: ready."):
            result = AssistantSession(followup_seconds=0).handle(
                "Leha ultra status",
                lambda _text: "brain should not run",
            )
        self.assertEqual(result.reply, "Pro mode: ready.")
        self.assertTrue(result.acted)

    def test_barge_status_reflex(self):
        from jarvis_ai.assistant_session import AssistantSession
        with patch("jarvis_ai.pro_ops.barge_in_status", return_value={"recommendation": "Keep barge-in off."}):
            result = AssistantSession(followup_seconds=0).handle(
                "Leha barge in status",
                lambda _text: "brain should not run",
            )
        self.assertEqual(result.reply, "Keep barge-in off.")

    def test_wake_validation_reflex(self):
        from jarvis_ai.assistant_session import AssistantSession
        with patch("jarvis_ai.pro_ops.wake_validation_status", return_value={
            "engine": "local_onnx",
            "threshold": 0.995,
        }):
            result = AssistantSession(followup_seconds=0).handle(
                "Leha wake validation",
                lambda _text: "brain should not run",
            )
        self.assertIn("local_onnx", result.reply)


if __name__ == "__main__":
    unittest.main(verbosity=2)
