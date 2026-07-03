"""Phase B tests: persistent conversation memory across restarts."""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from jarvis_ai import conversation_store


class TestConversationStore(unittest.TestCase):
    """Tests for the rolling conversation log."""

    def setUp(self):
        # Use a temp file for each test so tests are isolated.
        self._tmp = tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w"
        )
        self._tmp.close()
        self._store_patch = patch("jarvis_ai.conversation_store._STORE", new=__import__("pathlib").Path(self._tmp.name))
        self._store_patch.start()
        self.addCleanup(self._store_patch.stop)
        self._enabled = patch("jarvis_ai.config.CONVERSATION_PERSIST_ENABLED", True)
        self._enabled.start()
        self.addCleanup(self._enabled.stop)
        self._cap = patch("jarvis_ai.config.CONVERSATION_PERSIST_TURNS", 50)
        self._cap.start()
        self.addCleanup(self._cap.stop)
        self._semantic = patch("jarvis_ai.semantic_memory.remember_text_background")
        self._semantic.start()
        self.addCleanup(self._semantic.stop)

    def tearDown(self):
        try:
            os.unlink(self._tmp.name)
        except OSError:
            pass

    def test_empty_store_loads_nothing(self):
        self.assertEqual(conversation_store.load_recent(), [])

    def test_save_and_load_turn(self):
        conversation_store.save_turn("what is the weather", "It is raining, Sir.")
        turns = conversation_store.load_recent()
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0]["user"], "what is the weather")
        self.assertEqual(turns[0]["assistant"], "It is raining, Sir.")

    def test_empty_text_not_saved(self):
        conversation_store.save_turn("", "reply")
        conversation_store.save_turn("question", "")
        conversation_store.save_turn("   ", "  ")
        self.assertEqual(conversation_store.load_recent(), [])

    def test_rolling_cap(self):
        with patch("jarvis_ai.config.CONVERSATION_PERSIST_TURNS", 3):
            for i in range(5):
                conversation_store.save_turn(f"q{i}", f"a{i}")
            turns = conversation_store.load_recent()
            self.assertEqual(len(turns), 3)
            # Oldest turns dropped, most recent 3 kept.
            self.assertEqual(turns[0]["user"], "q2")
            self.assertEqual(turns[-1]["user"], "q4")

    def test_clear(self):
        conversation_store.save_turn("q", "a")
        self.assertEqual(len(conversation_store.load_recent()), 1)
        conversation_store.clear()
        self.assertEqual(conversation_store.load_recent(), [])

    def test_as_messages_format(self):
        conversation_store.save_turn("hello", "hi there")
        conversation_store.save_turn("how are you", "doing well")
        msgs = conversation_store.as_messages()
        self.assertEqual(len(msgs), 4)
        self.assertEqual(msgs[0], {"role": "user", "content": "hello"})
        self.assertEqual(msgs[1], {"role": "assistant", "content": "hi there"})
        self.assertEqual(msgs[2], {"role": "user", "content": "how are you"})
        self.assertEqual(msgs[3], {"role": "assistant", "content": "doing well"})

    def test_as_messages_respects_n(self):
        for i in range(5):
            conversation_store.save_turn(f"q{i}", f"a{i}")
        msgs = conversation_store.as_messages(n=2)
        # 2 turns -> 4 messages
        self.assertEqual(len(msgs), 4)

    def test_disabled_persistence_skips_save(self):
        with patch("jarvis_ai.config.CONVERSATION_PERSIST_ENABLED", False):
            conversation_store.save_turn("q", "a")
            self.assertEqual(conversation_store.load_recent(), [])

    def test_corrupt_file_returns_empty(self):
        # Write garbage to the store file.
        with open(self._tmp.name, "w", encoding="utf-8") as f:
            f.write("{not valid json")
        self.assertEqual(conversation_store.load_recent(), [])


class TestConversationClearReflex(unittest.TestCase):
    """The 'forget our conversation' local reflex."""

    def test_clear_conversation_command(self):
        from jarvis_ai.assistant_core import handle_local_intent
        with patch("jarvis_ai.conversation_store.clear") as mock_clear:
            result = handle_local_intent("forget our conversation")
        self.assertTrue(result.handled)
        self.assertEqual(result.reply, "Conversation cleared, Sir.")
        mock_clear.assert_called_once()

    def test_clear_history_command(self):
        from jarvis_ai.assistant_core import handle_local_intent
        with patch("jarvis_ai.conversation_store.clear") as mock_clear:
            result = handle_local_intent("clear history")
        self.assertTrue(result.handled)
        mock_clear.assert_called_once()

    def test_unrelated_command_not_intercepted(self):
        from jarvis_ai.assistant_core import handle_local_intent
        result = handle_local_intent("what is the weather")
        # Should fall through (not handled by the conversation-clear reflex).
        self.assertFalse(result.handled)


if __name__ == "__main__":
    unittest.main(verbosity=2)
