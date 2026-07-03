"""Pro-mode readiness tests: wake engine, health, and local status reflex."""
from __future__ import annotations

import unittest
from unittest.mock import patch


class TestProModeReadiness(unittest.TestCase):
    def test_health_reports_local_wake_when_available(self):
        from jarvis_ai import health
        with patch("jarvis_ai.wake_porcupine.is_available", return_value=False), \
             patch("jarvis_ai.wake_local_onnx.is_available", return_value=True), \
             patch("jarvis_ai.wake_openwakeword.is_available", return_value=False), \
             patch("sounddevice.query_devices", side_effect=RuntimeError("skip mic")):
            status = health.check()
        self.assertEqual(status["wake_engine"], "local_onnx")
        self.assertEqual(status["wake_reliable"], "ok")

    def test_health_reports_whisper_fallback_gap(self):
        from jarvis_ai import health
        with patch("jarvis_ai.wake_porcupine.is_available", return_value=False), \
             patch("jarvis_ai.wake_local_onnx.is_available", return_value=False), \
             patch("jarvis_ai.wake_openwakeword.is_available", return_value=False), \
             patch("sounddevice.query_devices", side_effect=RuntimeError("skip mic")):
            status = health.check()
        self.assertEqual(status["wake_engine"], "whisper_fallback")
        self.assertEqual(status["wake_reliable"], "missing")

    def test_pro_status_is_local_reflex(self):
        from jarvis_ai.assistant_session import AssistantSession
        with patch("jarvis_ai.pro_ops.spoken_status", return_value="Pro status: ready."):
            result = AssistantSession(followup_seconds=0).handle(
                "Leha pro status",
                lambda _text: "brain should not run",
            )
        self.assertTrue(result.acted)
        self.assertEqual(result.reply, "Pro status: ready.")


if __name__ == "__main__":
    unittest.main(verbosity=2)
