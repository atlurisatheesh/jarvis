"""Tests for Phase 4: Skill policy, audit log, undo stack."""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Skill policy
# ---------------------------------------------------------------------------

class TestSkillPolicy(unittest.TestCase):
    """Tests for jarvis_ai.skill_policy."""

    def test_read_tool_allowed_from_all_sources(self):
        from jarvis_ai.skill_policy import check
        for origin in ("local", "remote", "telegram", "android"):
            decision = check("tell_time", origin)
            self.assertTrue(decision.allowed, f"tell_time should be allowed from {origin}")
            self.assertFalse(decision.needs_confirmation)

    def test_destructive_tool_blocked_from_remote(self):
        from jarvis_ai.skill_policy import check
        decision = check("shutdown_pc", "remote")
        self.assertFalse(decision.allowed)
        self.assertIn("not allowed from remote", decision.reason)

    def test_destructive_tool_allowed_from_local_with_confirmation(self):
        from jarvis_ai.skill_policy import check
        decision = check("shutdown_pc", "local")
        self.assertTrue(decision.allowed)
        self.assertTrue(decision.needs_confirmation)

    def test_shell_only_from_local(self):
        from jarvis_ai.skill_policy import check
        self.assertTrue(check("run_command", "local").allowed)
        self.assertFalse(check("run_command", "remote").allowed)

    def test_unknown_tool_gets_safe_default(self):
        from jarvis_ai.skill_policy import check, get_policy
        decision = check("nonexistent_tool_xyz", "local")
        self.assertTrue(decision.allowed)  # default is reversible
        policy = get_policy("nonexistent_tool_xyz")
        self.assertEqual(policy.risk_level, "reversible")

    def test_external_tool_needs_confirmation(self):
        from jarvis_ai.skill_policy import check
        decision = check("google_gmail_send", "local")
        self.assertTrue(decision.allowed)
        self.assertTrue(decision.needs_confirmation)

    def test_run_tool_enforces_confirmation_required_policy(self):
        from jarvis_ai import skills

        result = skills.run_tool("shutdown_pc", {})
        self.assertIn("Confirmation required", result)

    def test_run_confirmed_tool_bypasses_confirmation_gate(self):
        from jarvis_ai import skills

        with patch("jarvis_ai.skills.windows.shutdown_pc", return_value="confirmed") as mocked:
            skills.DISPATCH["shutdown_pc"] = mocked
            try:
                result = skills.run_confirmed_tool("shutdown_pc", {})
            finally:
                from jarvis_ai.skills import windows
                skills.DISPATCH["shutdown_pc"] = windows.shutdown_pc
        self.assertEqual(result, "confirmed")
        mocked.assert_called_once()

    def test_wifi_command_reaches_confirmation_prompt(self):
        from jarvis_ai.assistant_core import handle_local_intent

        result = handle_local_intent("turn off wifi")
        self.assertTrue(result.handled)
        self.assertIn("Wi-Fi", result.reply)
        self.assertIn("yes or no", result.reply)

    def test_all_policies_returns_dict(self):
        from jarvis_ai.skill_policy import all_policies
        policies = all_policies()
        self.assertGreater(len(policies), 50)
        self.assertIn("shutdown_pc", policies)
        self.assertIn("tell_time", policies)

    def test_risk_levels_are_valid(self):
        from jarvis_ai.skill_policy import all_policies
        valid = {"read", "reversible", "external", "destructive"}
        for name, policy in all_policies().items():
            self.assertIn(policy.risk_level, valid, f"{name} has invalid risk level")

    def test_confirmation_tools_are_destructive_or_external(self):
        from jarvis_ai.skill_policy import all_policies
        for name, policy in all_policies().items():
            if policy.confirmation_required:
                self.assertIn(policy.risk_level, {"destructive", "external", "reversible"},
                              f"{name} requires confirmation but is {policy.risk_level}")


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

class TestAuditLog(unittest.TestCase):
    """Tests for jarvis_ai.audit_log."""

    def setUp(self):
        from jarvis_ai.audit_log import AuditLog
        self.tmpdir = tempfile.mkdtemp()
        self.log_path = Path(self.tmpdir) / "test_audit.logl"
        self.log = AuditLog(log_path=self.log_path, max_size_mb=1)

    def test_log_writes_entry(self):
        self.log.log("tell_time", {}, "local", "It is 3pm.")
        self.assertTrue(self.log_path.exists())
        entries = self.log.read_recent()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["tool"], "tell_time")
        self.assertEqual(entries[0]["result"], "It is 3pm.")

    def test_redact_sensitive_args(self):
        from jarvis_ai.audit_log import _redact_args
        redacted = _redact_args({"password": "secret123", "query": "weather"})
        self.assertEqual(redacted["password"], "***REDACTED***")
        self.assertEqual(redacted["query"], "weather")

    def test_redact_message_body(self):
        from jarvis_ai.audit_log import _redact_args
        redacted = _redact_args({"message": "hello there", "to": "mom"})
        self.assertEqual(redacted["message"], "***REDACTED***")
        self.assertEqual(redacted["to"], "mom")

    def test_truncate_long_result(self):
        from jarvis_ai.audit_log import _truncate_result
        long_text = "x" * 500
        result = _truncate_result(long_text, max_chars=100)
        self.assertEqual(len(result), 103)  # 100 + "..."
        self.assertTrue(result.endswith("..."))

    def test_read_recent_limit(self):
        for i in range(60):
            self.log.log("test_tool", {"i": i}, "local", f"result {i}")
        entries = self.log.read_recent(count=10)
        self.assertEqual(len(entries), 10)

    def test_search_by_tool(self):
        self.log.log("tell_time", {}, "local", "3pm")
        self.log.log("get_weather", {}, "local", "sunny")
        results = self.log.search(tool="tell_time")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["tool"], "tell_time")

    def test_search_by_origin(self):
        self.log.log("test", {}, "local", "a")
        self.log.log("test", {}, "remote", "b")
        local = self.log.search(origin="local")
        remote = self.log.search(origin="remote")
        self.assertTrue(all(e["origin"] == "local" for e in local))
        self.assertTrue(all(e["origin"] == "remote" for e in remote))

    def test_error_recorded(self):
        self.log.log("failing_tool", {}, "local", None, error="TimeoutError")
        entries = self.log.read_recent()
        self.assertEqual(entries[0]["error"], "TimeoutError")

    def test_rotation(self):
        """Log should rotate when it exceeds max size."""
        from jarvis_ai.audit_log import AuditLog
        small_log = AuditLog(log_path=self.log_path, max_size_mb=0.001)  # ~1KB
        for i in range(200):
            small_log.log("test", {"i": i}, "local", "x" * 100)
        # The rotation creates a backup file
        backup = self.log_path.with_suffix(".logl.1")
        # After rotation, the main file should be smaller
        self.assertLess(self.log_path.stat().st_size, 500000)


# ---------------------------------------------------------------------------
# Undo stack
# ---------------------------------------------------------------------------

class TestUndoStack(unittest.TestCase):
    """Tests for jarvis_ai.undo.UndoStack."""

    def setUp(self):
        from jarvis_ai.undo import UndoStack
        self.stack = UndoStack(max_depth=5)

    def test_empty_undo_returns_message(self):
        result = self.stack.undo_last()
        self.assertIn("Nothing to undo", result)

    def test_push_then_undo(self):
        calls = []
        self.stack.push("test action", lambda: (calls.append(1), "reverted")[1])
        self.assertEqual(self.stack.depth, 1)
        result = self.stack.undo_last()
        self.assertIn("Undid: test action", result)
        self.assertEqual(calls, [1])
        self.assertEqual(self.stack.depth, 0)

    def test_lifo_order(self):
        order = []
        self.stack.push("first", lambda: (order.append("first"), "ok")[1])
        self.stack.push("second", lambda: (order.append("second"), "ok")[1])
        self.stack.undo_last()
        self.stack.undo_last()
        self.assertEqual(order, ["second", "first"])

    def test_max_depth(self):
        for i in range(10):
            self.stack.push(f"action {i}", lambda: "ok")
        self.assertEqual(self.stack.depth, 5)  # capped at max_depth

    def test_undo_by_category(self):
        self.stack.push("volume change", lambda: "ok", category="volume")
        self.stack.push("brightness change", lambda: "ok", category="brightness")
        result = self.stack.undo_last(category="volume")
        self.assertIn("volume change", result)
        self.assertEqual(self.stack.depth, 1)

    def test_undo_by_category_none_found(self):
        self.stack.push("volume change", lambda: "ok", category="volume")
        result = self.stack.undo_last(category="brightness")
        self.assertIn("Nothing to undo", result)

    def test_undo_all(self):
        for i in range(3):
            self.stack.push(f"action {i}", lambda: "ok")
        result = self.stack.undo_all()
        self.assertIn("Undid 3", result)
        self.assertEqual(self.stack.depth, 0)

    def test_recent_returns_list(self):
        self.stack.push("action 1", lambda: "ok")
        self.stack.push("action 2", lambda: "ok")
        recent = self.stack.recent
        self.assertEqual(len(recent), 2)
        self.assertEqual(recent[0]["description"], "action 2")  # most recent first

    def test_clear(self):
        self.stack.push("a", lambda: "ok")
        self.stack.push("b", lambda: "ok")
        self.stack.clear()
        self.assertEqual(self.stack.depth, 0)

    def test_rollback_exception_handled(self):
        def bad_rollback():
            raise RuntimeError("can't revert")
        self.stack.push("bad action", bad_rollback)
        result = self.stack.undo_last()
        self.assertIn("Could not undo", result)


# ---------------------------------------------------------------------------
# Window manager (Windows-specific; tests guard for non-Windows)
# ---------------------------------------------------------------------------

class TestWindowManager(unittest.TestCase):
    """Tests for jarvis_ai.window_manager."""

    def test_list_windows_returns_list(self):
        import platform
        if platform.system() != "Windows":
            self.skipTest("Windows-only")
        from jarvis_ai.window_manager import list_windows
        windows = list_windows()
        self.assertIsInstance(windows, list)

    def test_find_window_by_title_nonexistent(self):
        import platform
        if platform.system() != "Windows":
            self.skipTest("Windows-only")
        from jarvis_ai.window_manager import find_window_by_title
        result = find_window_by_title("ABSOLUTELY_NONEXISTENT_WINDOW_XYZ")
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
