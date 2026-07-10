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
        self.assertEqual(status["wake_engine"], "strict_transcript")
        self.assertEqual(status["wake_reliable"], "limited")

    def test_pro_status_is_local_reflex(self):
        from jarvis_ai.assistant_session import AssistantSession
        with patch("jarvis_ai.pro_ops.spoken_status", return_value="Pro status: ready."):
            result = AssistantSession(followup_seconds=0).handle(
                "Leha pro status",
                lambda _text: "brain should not run",
            )
        self.assertTrue(result.acted)
        self.assertEqual(result.reply, "Pro status: ready.")

    def test_siri_parity_status_is_local_reflex(self):
        from jarvis_ai.assistant_session import AssistantSession
        with patch("jarvis_ai.pro_ops.spoken_siri_parity_status", return_value="Not fully Siri level yet."):
            result = AssistantSession(followup_seconds=0).handle(
                "Leha Siri status",
                lambda _text: "brain should not run",
            )
        self.assertTrue(result.acted)
        self.assertEqual(result.reply, "Not fully Siri level yet.")

    def test_wake_data_status_is_local_reflex(self):
        from jarvis_ai.assistant_session import AssistantSession
        with patch("jarvis_ai.pro_ops.spoken_wake_data_status", return_value="Wake data: 1 positive."):
            result = AssistantSession(followup_seconds=0).handle(
                "Leha wake data status",
                lambda _text: "brain should not run",
            )
        self.assertTrue(result.acted)
        self.assertEqual(result.reply, "Wake data: 1 positive.")

    def test_barge_in_enable_blocked_without_aec(self):
        from jarvis_ai.assistant_session import AssistantSession
        with patch("jarvis_ai.pro_ops.barge_in_status", return_value={"safe_to_enable": False}):
            result = AssistantSession(followup_seconds=0).handle(
                "Leha enable barge in",
                lambda _text: "brain should not run",
            )
        self.assertTrue(result.acted)
        self.assertIn("cannot safely enable", result.reply)

    def test_pro_settings_refuse_barge_in_without_aec(self):
        from jarvis_ai import pro_settings
        import tempfile
        from pathlib import Path

        tmp = Path(tempfile.mkdtemp()) / "pro_settings.json"
        with patch("jarvis_ai.pro_settings._PATH", tmp), \
             patch("jarvis_ai.pro_settings.config.AEC_HARDWARE_DEVICE", None):
            data = pro_settings.save({"barge_in_enabled": True, "aec_enabled": False})
        self.assertFalse(data["barge_in_enabled"])
        self.assertIn("AEC", data["barge_in_note"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
