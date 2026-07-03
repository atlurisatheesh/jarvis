"""Tests for Phases B-E: persistent memory, semantic recall, notifier, health gate."""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch


class TestPersistentConversationMemory(unittest.TestCase):
    def test_save_load_as_messages_and_clear(self):
        from jarvis_ai import conversation_store
        with tempfile.TemporaryDirectory() as td, \
             patch.object(conversation_store, "_STORE", Path(td) / "conversation.json"), \
             patch("jarvis_ai.semantic_memory.remember_text_background"):
            conversation_store.save_turn("hello", "hi")
            conversation_store.save_turn("what is my project", "Leha")
            recent = conversation_store.load_recent(2)
            self.assertEqual(len(recent), 2)
            msgs = conversation_store.as_messages(2)
            self.assertEqual(msgs[0]["role"], "user")
            self.assertEqual(msgs[1]["role"], "assistant")
            self.assertIn("hello", conversation_store.summary())
            conversation_store.clear()
            self.assertEqual(conversation_store.load_recent(), [])

    def test_save_turn_caps_history(self):
        from jarvis_ai import conversation_store
        with tempfile.TemporaryDirectory() as td, \
             patch.object(conversation_store, "_STORE", Path(td) / "conversation.json"), \
             patch("jarvis_ai.config.CONVERSATION_PERSIST_TURNS", 2), \
             patch("jarvis_ai.semantic_memory.remember_text_background"):
            for i in range(4):
                conversation_store.save_turn(f"u{i}", f"a{i}")
            self.assertEqual([t["user"] for t in conversation_store.load_recent(10)], ["u2", "u3"])


class TestSemanticMemory(unittest.TestCase):
    def test_context_for_formats_results(self):
        from jarvis_ai import semantic_memory
        with patch.object(semantic_memory, "recall", return_value=["one", "two"]):
            self.assertIn("Relevant memory", semantic_memory.context_for("x"))

    def test_structured_memory_falls_back_to_exact_recall(self):
        from jarvis_ai import structured_memory
        with tempfile.TemporaryDirectory() as td, \
             patch.object(structured_memory, "_STORE", Path(td) / "structured.json"), \
             patch("jarvis_ai.semantic_memory.remember_text_background"), \
             patch("jarvis_ai.semantic_memory.recall", return_value=[]):
            structured_memory.remember("passport is in blue bag")
            result = structured_memory.semantic_recall("passport")
            self.assertIn("passport is in blue bag", result)


class TestNotifier(unittest.TestCase):
    def tearDown(self):
        from jarvis_ai import notifier
        notifier.clear()
        notifier.unregister_speaker()

    def test_notify_uses_registered_speaker(self):
        from jarvis_ai import notifier

        class Speaker:
            def __init__(self):
                self.spoken = []

            def say(self, text):
                self.spoken.append(text)

        speaker = Speaker()
        notifier.register_speaker(speaker)
        self.assertTrue(notifier.notify("Job done", source="reminder:unit"))
        self.assertEqual(speaker.spoken, ["Job done"])
        self.assertIn("Job done", notifier.pending_summary())

    def test_background_job_announces_without_custom_callback(self):
        from jarvis_ai import background_jobs, notifier
        spoken = []

        class Speaker:
            def say(self, text):
                spoken.append(text)

        notifier.register_speaker(Speaker())
        bg = background_jobs.BackgroundJobs(max_workers=1)
        bg.submit("unit job", lambda: "finished")
        deadline = time.time() + 2
        while time.time() < deadline and not spoken:
            time.sleep(0.02)
        bg.shutdown()
        self.assertTrue(any("unit job is done" in s for s in spoken))


class TestStartupHealthGate(unittest.TestCase):
    def test_startup_gate_ok_when_required_parts_ready(self):
        from jarvis_ai import health
        status = {
            "mic_configured": "ok",
            "deepgram_key": "ok",
            "openai_key": "missing",
            "groq_key": "missing",
            "ollama": "ok",
        }
        with patch.object(health, "check", return_value=status), \
             patch.object(health, "mic_self_test", return_value={"ok": True}):
            ok, issues = health.startup_gate()
        self.assertTrue(ok)
        self.assertEqual(issues, [])

    def test_startup_gate_reports_missing_mic(self):
        from jarvis_ai import health
        status = {
            "mic_configured": "missing",
            "deepgram_key": "ok",
            "openai_key": "missing",
            "groq_key": "missing",
            "ollama": "ok",
        }
        with patch.object(health, "check", return_value=status), \
             patch.object(health, "mic_self_test", return_value={"ok": False}):
            ok, issues = health.startup_gate()
        self.assertFalse(ok)
        self.assertIn("microphone", issues)


if __name__ == "__main__":
    unittest.main(verbosity=2)
