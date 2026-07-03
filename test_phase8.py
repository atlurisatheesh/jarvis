"""Tests for Phase 8: structured_memory + summarizer."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class TestStructuredMemory(unittest.TestCase):
    def setUp(self):
        from jarvis_ai import structured_memory
        self.sm = structured_memory
        self.tmp = Path(tempfile.mkdtemp()) / "structured_memory.json"
        self._p = patch.object(structured_memory, "_STORE", self.tmp)
        self._p.start()

    def tearDown(self):
        self._p.stop()

    def test_remember_and_recall(self):
        self.sm.remember("my car is a blue Swift", "fact")
        hits = self.sm.recall(mem_type="fact")
        self.assertEqual(len(hits), 1)
        self.assertIn("Swift", hits[0]["text"])

    def test_empty_text_rejected(self):
        out = self.sm.remember("   ", "fact")
        self.assertIn("Nothing", out)
        self.assertEqual(self.sm.recall(), [])

    def test_unknown_type_defaults_to_fact(self):
        self.sm.remember("something", "garbage")
        self.assertEqual(self.sm.recall()[0]["type"], "fact")

    def test_keyed_preference_overwrites(self):
        self.sm.remember("celsius", "preference", key="units")
        self.sm.remember("fahrenheit", "preference", key="units")
        prefs = self.sm.recall(mem_type="preference")
        self.assertEqual(len(prefs), 1)
        self.assertEqual(prefs[0]["text"], "fahrenheit")

    def test_recall_filters_by_query(self):
        self.sm.remember("likes tea", "preference")
        self.sm.remember("car is blue", "fact")
        self.assertEqual(len(self.sm.recall(query="tea")), 1)

    def test_summary_groups_by_type(self):
        self.sm.remember("car is blue", "fact")
        self.sm.remember("brief answers", "preference")
        s = self.sm.summary()
        self.assertIn("fact", s)
        self.assertIn("preference", s)

    def test_summary_empty(self):
        self.assertIn("nothing", self.sm.summary().lower())

    def test_forget_by_query(self):
        self.sm.remember("car is blue", "fact")
        self.sm.remember("likes tea", "preference")
        out = self.sm.forget(query="tea")
        self.assertIn("Forgot 1", out)
        self.assertEqual(len(self.sm.recall()), 1)

    def test_forget_no_match(self):
        self.sm.remember("car is blue", "fact")
        out = self.sm.forget(query="spaceship")
        self.assertIn("Nothing", out)
        self.assertEqual(len(self.sm.recall()), 1)

    def test_forget_by_type(self):
        self.sm.remember("car is blue", "fact")
        self.sm.remember("brief answers", "preference")
        self.sm.forget(mem_type="fact")
        self.assertEqual([e["type"] for e in self.sm.recall()], ["preference"])

    def test_export_all(self):
        self.sm.remember("a", "fact")
        self.sm.remember("b", "task")
        self.assertEqual(len(self.sm.export_all()), 2)

    def test_skills_registered(self):
        names = {s[0]["name"] for s in self.sm.SKILLS}
        self.assertEqual(names, {
            "remember_this",
            "what_do_you_remember",
            "semantic_memory_recall",
            "forget_that",
        })


class TestSummarizer(unittest.TestCase):
    def setUp(self):
        from jarvis_ai import summarizer
        self.s = summarizer

    def test_short_text_unchanged(self):
        text = "One sentence only."
        self.assertEqual(self.s.summarize(text, max_sentences=3), "One sentence only.")

    def test_empty(self):
        self.assertEqual(self.s.summarize(""), "")

    def test_caps_sentence_count(self):
        text = ("The orchard has mango trees. The mango trees need water daily. "
                "Coconut palms are tall. Bananas ripen fast. Sapota is sweet. "
                "Mango disease is sooty mould.")
        out = self.s.summarize(text, max_sentences=2)
        # At most 2 sentences kept.
        self.assertLessEqual(out.count(".") , 2)
        self.assertTrue(len(out) < len(text))

    def test_summarize_turns(self):
        turns = [
            {"role": "user", "text": "Remind me to water the mango trees tomorrow morning."},
            {"role": "assistant", "text": "Reminder set for the mango trees."},
            {"role": "user", "text": "Also the coconut palms need fertilizer."},
        ]
        out = self.s.summarize_turns(turns, max_sentences=2)
        self.assertTrue(len(out) > 0)

    def test_summarize_turns_empty(self):
        self.assertEqual(self.s.summarize_turns([]), "")

    def test_with_brain_falls_back_on_error(self):
        text = ("The orchard has mango trees. The mango trees need water. "
                "Coconut palms are tall. Bananas ripen fast.")
        with patch("jarvis_ai.brain.Brain", side_effect=RuntimeError("offline")):
            out = self.s.summarize_with_brain(text, max_sentences=2)
            # Falls back to extractive (non-empty, shorter than input).
            self.assertTrue(out)
            self.assertLessEqual(len(out), len(text))


if __name__ == "__main__":
    unittest.main()
