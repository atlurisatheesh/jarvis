"""Tests for Phase 7: Home Assistant stub + named routines."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch


class TestHomeAssistantNotConfigured(unittest.TestCase):
    """With no token/URL, nothing is contacted and messages are graceful."""

    def setUp(self):
        from jarvis_ai import home_assistant
        self.ha = home_assistant
        self._p = patch("jarvis_ai.config.HOME_ASSISTANT_ENABLED", False)
        self._p.start()

    def tearDown(self):
        self._p.stop()

    def test_is_configured_false(self):
        self.assertFalse(self.ha.is_configured())

    def test_ping_not_configured(self):
        self.assertIn("not configured", self.ha.ping().lower())

    def test_list_not_configured(self):
        self.assertIn("not configured", self.ha.list_entities("light").lower())

    def test_turn_on_not_configured(self):
        self.assertIn("not configured", self.ha.turn_on("light.x").lower())

    def test_no_network_call_when_unconfigured(self):
        # If requests were touched while unconfigured that would be a bug.
        with patch("jarvis_ai.home_assistant._get") as g:
            self.ha.ping()
            g.assert_not_called()


class TestHomeAssistantConfigured(unittest.TestCase):
    """With config flag on, calls hit the (mocked) HA HTTP helpers."""

    def setUp(self):
        from jarvis_ai import home_assistant
        self.ha = home_assistant
        self._p = patch("jarvis_ai.config.HOME_ASSISTANT_ENABLED", True)
        self._p.start()

    def tearDown(self):
        self._p.stop()

    def test_ping_ok(self):
        resp = MagicMock(status_code=200)
        with patch("jarvis_ai.home_assistant._get", return_value=resp):
            self.assertIn("connected", self.ha.ping().lower())

    def test_list_filters_domain(self):
        resp = MagicMock(status_code=200)
        resp.json.return_value = [
            {"entity_id": "light.living"}, {"entity_id": "switch.fan"},
            {"entity_id": "light.kitchen"},
        ]
        with patch("jarvis_ai.home_assistant._get", return_value=resp):
            out = self.ha.list_entities("light")
            self.assertIn("light.living", out)
            self.assertNotIn("switch.fan", out)

    def test_turn_on_calls_service(self):
        resp = MagicMock(status_code=200)
        with patch("jarvis_ai.home_assistant._post", return_value=resp) as post:
            out = self.ha.turn_on("light.living")
            self.assertIn("Done", out)
            post.assert_called_once()

    def test_scene_prefixes_id(self):
        resp = MagicMock(status_code=200)
        with patch("jarvis_ai.home_assistant._post", return_value=resp) as post:
            self.ha.activate_scene("movie")
            path = post.call_args[0][0]
            self.assertIn("scene", path)

    def test_network_error_is_readable(self):
        with patch("jarvis_ai.home_assistant._get", side_effect=OSError("boom")):
            out = self.ha.ping()
            self.assertIn("unreachable", out.lower())

    def test_skills_registered(self):
        names = {s[0]["name"] for s in self.ha.SKILLS}
        self.assertEqual(names, {
            "home_assistant_ping", "home_assistant_list",
            "home_assistant_turn_on", "home_assistant_turn_off",
            "home_assistant_scene",
        })


class TestNamedRoutines(unittest.TestCase):
    def test_named_routines_present(self):
        from jarvis_ai import config
        for name in ("good morning", "work mode", "movie mode", "leaving home", "good night"):
            self.assertIn(name, config.ROUTINES, f"missing routine {name}")

    def test_existing_routines_preserved(self):
        from jarvis_ai import config
        # The original two must still be intact (no-disturb guarantee).
        self.assertIn("good morning", config.ROUTINES)
        self.assertIn("work", config.ROUTINES)

    def test_routine_runs_named(self):
        from jarvis_ai.skills import routines
        with patch("jarvis_ai.skills.system.open_app"), \
             patch("jarvis_ai.skills.web.open_url"):
            out = routines.run_routine("movie mode")
            self.assertIn("movie mode", out.lower())


if __name__ == "__main__":
    unittest.main()
