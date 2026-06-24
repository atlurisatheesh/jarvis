"""Tests for Phase 9: version system + ops artifacts."""
from __future__ import annotations

import re
import unittest
from pathlib import Path


class TestVersion(unittest.TestCase):
    def test_version_file_exists(self):
        vf = Path(__file__).parent / "jarvis_ai" / "VERSION"
        self.assertTrue(vf.exists())

    def test_version_is_semver(self):
        from jarvis_ai import config
        self.assertRegex(config.LEHA_VERSION, r"^\d+\.\d+\.\d+$")

    def test_version_matches_file(self):
        from jarvis_ai import config
        vf = Path(__file__).parent / "jarvis_ai" / "VERSION"
        self.assertEqual(config.LEHA_VERSION, vf.read_text(encoding="utf-8").strip())

    def test_build_tag_still_present(self):
        # Human build tag must not have been removed (no-disturb).
        from jarvis_ai import config
        self.assertTrue(config.LEHA_BUILD)


class TestChangelog(unittest.TestCase):
    def test_changelog_exists_and_lists_version(self):
        from jarvis_ai import config
        cl = Path(__file__).parent / "CHANGELOG.md"
        self.assertTrue(cl.exists())
        text = cl.read_text(encoding="utf-8")
        self.assertIn(config.LEHA_VERSION, text)


class TestRunner(unittest.TestCase):
    def test_runner_script_exists(self):
        rs = Path(__file__).parent / "scripts" / "run_tests.ps1"
        self.assertTrue(rs.exists())

    def test_runner_references_phase_tests(self):
        rs = Path(__file__).parent / "scripts" / "run_tests.ps1"
        text = rs.read_text(encoding="utf-8")
        self.assertIn("test_phase", text)


if __name__ == "__main__":
    unittest.main()
