"""Dashboard polish and Windows packaging regression tests."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class TestProSettings(unittest.TestCase):
    def test_save_load_clamps_threshold_and_keeps_safe_shape(self):
        from jarvis_ai import pro_settings
        with tempfile.TemporaryDirectory() as td, \
             patch.object(pro_settings, "_PATH", Path(td) / "pro_settings.json"):
            saved = pro_settings.save({
                "custom_wake_threshold": 2.0,
                "barge_in_enabled": True,
                "proactive_max_spoken_per_hour": 99,
            })
            loaded = pro_settings.load()
        self.assertEqual(saved["custom_wake_threshold"], 0.9999)
        self.assertFalse(loaded["barge_in_enabled"])
        self.assertIn("requires validated AEC", loaded["barge_in_note"])
        self.assertEqual(loaded["proactive_max_spoken_per_hour"], 60)

    def test_apply_to_config_updates_current_process(self):
        from jarvis_ai import pro_settings, config
        with tempfile.TemporaryDirectory() as td, \
             patch.object(pro_settings, "_PATH", Path(td) / "pro_settings.json"):
            pro_settings.save({"custom_wake_threshold": 0.91, "barge_in_enabled": False})
            applied = pro_settings.apply_to_config()
        self.assertEqual(applied["custom_wake_threshold"], 0.91)
        self.assertEqual(config.CUSTOM_WAKE_THRESHOLD, 0.91)


class TestDashboardAssets(unittest.TestCase):
    def test_dashboard_html_contains_live_controls(self):
        html = Path("jarvis_ai/web/dashboard.html").read_text(encoding="utf-8")
        self.assertIn("/api/pro/status", html)
        self.assertIn("/api/pro/settings", html)
        self.assertIn("setInterval", html)
        self.assertIn("Wake threshold", html)
        self.assertIn("Barge-in", html)

    def test_packaging_scripts_exist(self):
        for name in (
            "start_leha.ps1",
            "stop_leha.ps1",
            "restart_leha.ps1",
            "status_leha.ps1",
            "install_autostart.ps1",
            "uninstall_autostart.ps1",
            "start_tray.ps1",
        ):
            self.assertTrue((Path("scripts") / name).is_file(), name)

    def test_packaging_scripts_do_not_use_power_commands(self):
        forbidden = ("shutdown", "restart-computer", "stop-computer", "rundll32.exe powrprof")
        for path in Path("scripts").glob("*leha*.ps1"):
            text = path.read_text(encoding="utf-8").lower()
            for word in forbidden:
                self.assertNotIn(word, text, str(path))

    def test_wake_ack_is_enabled_for_cached_clone_response(self):
        from jarvis_ai import config
        self.assertTrue(config.SPEAK_WAKE_ACK)
        self.assertIn("yes sir", config.ELEVENLABS_CACHE_PHRASES)


if __name__ == "__main__":
    unittest.main(verbosity=2)
