"""Tests for Phase 0: log management, token redaction, supervisor health check."""
from __future__ import annotations

import datetime as dt
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Token redaction
# ---------------------------------------------------------------------------

class TestRedaction(unittest.TestCase):
    def test_redacts_bearer_token(self):
        from jarvis_ai.log_manager import redact
        out = redact("Authorization: Bearer sk-abc123def456ghi789")
        self.assertIn("[REDACTED]", out)
        self.assertNotIn("sk-abc123def456ghi789", out)

    def test_redacts_key_equals_value(self):
        from jarvis_ai.log_manager import redact
        out = redact("api_key=AIzaSyB1234567890abcdefghij")
        self.assertIn("[REDACTED]", out)
        self.assertNotIn("AIzaSyB1234567890", out)

    def test_redacts_password_label(self):
        from jarvis_ai.log_manager import redact
        out = redact("password=supersecret123")
        self.assertIn("[REDACTED]", out)
        self.assertNotIn("supersecret123", out)

    def test_redacts_jwt_token(self):
        from jarvis_ai.log_manager import redact
        jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.sflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        out = redact(f"token: {jwt}")
        self.assertIn("[REDACTED]", out)
        self.assertNotIn(jwt, out)

    def test_redacts_google_oauth_token(self):
        from jarvis_ai.log_manager import redact
        out = redact("ya29.a0ARrdaM-abcdefghijklmnopqrstuvwxyz123456")
        self.assertIn("[REDACTED]", out)
        self.assertNotIn("ya29.a0ARrdaM", out)

    def test_redacts_app_password(self):
        from jarvis_ai.log_manager import redact
        out = redact("app password is abcd-efgh-ijkl-mnop")
        self.assertIn("[REDACTED]", out)
        self.assertNotIn("abcd-efgh-ijkl-mnop", out)

    def test_preserves_normal_text(self):
        from jarvis_ai.log_manager import redact
        msg = "[heartbeat] state=idle turns=3 age=12s"
        self.assertEqual(redact(msg), msg)

    def test_preserves_short_values(self):
        from jarvis_ai.log_manager import redact
        # Short values after labels should not be aggressively redacted
        out = redact("volume=50 brightness=80")
        self.assertNotIn("[REDACTED]", out)

    def test_redact_empty(self):
        from jarvis_ai.log_manager import redact
        self.assertEqual(redact(""), "")


# ---------------------------------------------------------------------------
# Log writing and rotation
# ---------------------------------------------------------------------------

class TestLogWriting(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._patch = patch("jarvis_ai.log_manager._log_path",
                            return_value=Path(self._tmp) / "test.log")
        self._patch.start()

    def tearDown(self):
        self._patch.stop()

    def test_log_writes_redacted_line(self):
        from jarvis_ai import log_manager
        log_manager.log("Authorization: Bearer sk-secretkey123456", component="test")
        content = (Path(self._tmp) / "test.log").read_text(encoding="utf-8")
        self.assertIn("[REDACTED]", content)
        self.assertNotIn("sk-secretkey123456", content)
        self.assertIn("[test]", content)

    def test_log_includes_timestamp(self):
        from jarvis_ai import log_manager
        log_manager.log("test message", component="unit")
        content = (Path(self._tmp) / "test.log").read_text(encoding="utf-8")
        # YYYY-MM-DD HH:MM:SS pattern
        import re
        self.assertRegex(content, r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")

    def test_read_recent_returns_lines(self):
        from jarvis_ai import log_manager
        for i in range(5):
            log_manager.log(f"line {i}", component="t")
        lines = log_manager.read_recent(count=3)
        self.assertEqual(len(lines), 3)
        self.assertIn("line 4", lines[-1])

    def test_rotation_on_oversize(self):
        from jarvis_ai import log_manager
        with patch("jarvis_ai.log_manager._max_bytes", return_value=500):
            for i in range(50):
                log_manager.log(f"padding-{i}-" + "x" * 30, component="rot")
            content = (Path(self._tmp) / "test.log").read_text(encoding="utf-8")
            # After rotation, the main log should be small (just the new line(s))
            self.assertLess(len(content), 500)


# ---------------------------------------------------------------------------
# Log retention cleanup
# ---------------------------------------------------------------------------

class TestRetentionCleanup(unittest.TestCase):
    def test_cleanup_removes_old_files(self):
        from jarvis_ai import log_manager
        with tempfile.TemporaryDirectory() as tmp:
            old_log = Path(tmp) / "old.log"
            old_log.write_text("old content")
            # Set mtime to 30 days ago
            old_time = time.time() - 30 * 86400
            os.utime(old_log, (old_time, old_time))
            with patch("jarvis_ai.log_manager._log_dir", return_value=Path(tmp)):
                with patch("jarvis_ai.log_manager._retention_days", return_value=7):
                    removed = log_manager.cleanup_old_logs()
            self.assertEqual(removed, 1)
            self.assertFalse(old_log.exists())

    def test_cleanup_keeps_recent_files(self):
        from jarvis_ai import log_manager
        with tempfile.TemporaryDirectory() as tmp:
            recent = Path(tmp) / "recent.log"
            recent.write_text("recent")
            with patch("jarvis_ai.log_manager._log_dir", return_value=Path(tmp)):
                with patch("jarvis_ai.log_manager._retention_days", return_value=7):
                    removed = log_manager.cleanup_old_logs()
            self.assertEqual(removed, 0)
            self.assertTrue(recent.exists())


# ---------------------------------------------------------------------------
# Supervisor health check
# ---------------------------------------------------------------------------

class TestSupervisorHealthCheck(unittest.TestCase):
    def test_health_check_returns_int(self):
        from jarvis_ai import supervisor
        with patch("jarvis_ai.health.summary", return_value="ok"):
            with patch("jarvis_ai.health.check", return_value={"mic": True, "brain": True}):
                code = supervisor.health_check()
        self.assertIsInstance(code, int)

    def test_health_check_zero_on_healthy(self):
        from jarvis_ai import supervisor
        with patch("jarvis_ai.health.summary", return_value="ok"):
            with patch("jarvis_ai.health.check", return_value={"mic": True, "net": True}):
                code = supervisor.health_check()
        self.assertEqual(code, 0)

    def test_health_check_nonzero_on_failure(self):
        from jarvis_ai import supervisor
        with patch("jarvis_ai.health.summary", return_value="partial"):
            with patch("jarvis_ai.health.check", return_value={"mic": True, "brain": False}):
                code = supervisor.health_check()
        self.assertEqual(code, 1)

    def test_startup_housekeeping_does_not_crash(self):
        from jarvis_ai import supervisor
        supervisor._startup_housekeeping()  # should not raise


if __name__ == "__main__":
    unittest.main(verbosity=2)
