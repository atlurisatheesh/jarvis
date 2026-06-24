"""Tests for Phase 6: device_manager (pairing, sessions, rate limit, capabilities)."""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch


def _fresh_manager(ttl=3600, rate=60):
    """A DeviceManager backed by a throwaway store path."""
    from jarvis_ai import device_manager
    tmp = Path(tempfile.mkdtemp()) / "devices.json"
    patcher = patch.object(device_manager, "_STORE", tmp)
    patcher.start()
    mgr = device_manager.DeviceManager(session_ttl=ttl, rate_limit=rate)
    return mgr, patcher


class TestPairing(unittest.TestCase):
    def setUp(self):
        self.mgr, self._p = _fresh_manager()

    def tearDown(self):
        self._p.stop()

    def test_new_device_is_pending(self):
        dev = self.mgr.request_pairing("dev1", "Phone")
        self.assertEqual(dev.status, "pending")
        self.assertIn(dev, self.mgr.pending())

    def test_request_pairing_idempotent(self):
        self.mgr.request_pairing("dev1", "Phone")
        self.mgr.request_pairing("dev1", "Phone")
        self.assertEqual(len(self.mgr.list_devices()), 1)

    def test_approve_then_not_pending(self):
        self.mgr.request_pairing("dev1")
        self.assertTrue(self.mgr.approve("dev1"))
        self.assertEqual(self.mgr.pending(), [])

    def test_approve_unknown_device_fails(self):
        self.assertFalse(self.mgr.approve("ghost"))

    def test_revoke_drops_status_and_sessions(self):
        self.mgr.request_pairing("dev1")
        self.mgr.approve("dev1")
        tok = self.mgr.open_session("dev1")
        self.assertIsNotNone(tok)
        self.assertTrue(self.mgr.revoke("dev1"))
        self.assertIsNone(self.mgr.session_device(tok))


class TestSessions(unittest.TestCase):
    def setUp(self):
        self.mgr, self._p = _fresh_manager()

    def tearDown(self):
        self._p.stop()

    def test_session_only_for_approved(self):
        self.mgr.request_pairing("dev1")
        self.assertIsNone(self.mgr.open_session("dev1"))  # pending
        self.mgr.approve("dev1")
        self.assertIsNotNone(self.mgr.open_session("dev1"))

    def test_session_resolves_device(self):
        self.mgr.request_pairing("dev1")
        self.mgr.approve("dev1")
        tok = self.mgr.open_session("dev1")
        self.assertEqual(self.mgr.session_device(tok), "dev1")

    def test_session_expires(self):
        mgr, p = _fresh_manager(ttl=0)
        try:
            mgr.request_pairing("dev1")
            mgr.approve("dev1")
            tok = mgr.open_session("dev1")
            time.sleep(0.01)
            self.assertIsNone(mgr.session_device(tok))
        finally:
            p.stop()

    def test_invalid_token(self):
        self.assertIsNone(self.mgr.session_device("nope"))


class TestRateLimitAndCaps(unittest.TestCase):
    def setUp(self):
        self.mgr, self._p = _fresh_manager(rate=3)

    def tearDown(self):
        self._p.stop()

    def test_rate_limit_blocks_over_cap(self):
        self.mgr.request_pairing("dev1")
        self.mgr.approve("dev1")
        self.assertTrue(self.mgr.allow_request("dev1"))
        self.assertTrue(self.mgr.allow_request("dev1"))
        self.assertTrue(self.mgr.allow_request("dev1"))
        self.assertFalse(self.mgr.allow_request("dev1"))  # 4th over cap of 3

    def test_default_caps_are_safe_only(self):
        from jarvis_ai import device_manager
        self.mgr.request_pairing("dev1")
        self.mgr.approve("dev1")
        self.assertTrue(self.mgr.has_capability("dev1", "read"))
        self.assertFalse(self.mgr.has_capability("dev1", "destructive"))

    def test_destructive_caps_stripped_on_approve(self):
        self.mgr.request_pairing("dev1")
        self.mgr.approve("dev1", capabilities=["read", "destructive", "control"])
        self.assertTrue(self.mgr.has_capability("dev1", "read"))
        self.assertFalse(self.mgr.has_capability("dev1", "destructive"))
        self.assertFalse(self.mgr.has_capability("dev1", "control"))

    def test_authorize_full_gate(self):
        self.mgr.request_pairing("dev1")
        self.mgr.approve("dev1")
        tok = self.mgr.open_session("dev1")
        ok, reason = self.mgr.authorize(tok, "read")
        self.assertTrue(ok)
        self.assertEqual(reason, "")
        ok2, reason2 = self.mgr.authorize(tok, "destructive")
        self.assertFalse(ok2)
        self.assertIn("capability", reason2)

    def test_authorize_invalid_session(self):
        ok, reason = self.mgr.authorize("bad-token", "read")
        self.assertFalse(ok)
        self.assertIn("session", reason)


class TestPersistence(unittest.TestCase):
    def test_devices_persist_across_instances(self):
        from jarvis_ai import device_manager
        tmp = Path(tempfile.mkdtemp()) / "devices.json"
        with patch.object(device_manager, "_STORE", tmp):
            m1 = device_manager.DeviceManager()
            m1.request_pairing("dev1", "Phone")
            m1.approve("dev1")
            m2 = device_manager.DeviceManager()  # reload from disk
            ids = [d.device_id for d in m2.list_devices()]
            self.assertIn("dev1", ids)


if __name__ == "__main__":
    unittest.main()
