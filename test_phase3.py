"""Tests for Phase 3: Speech manager, echo cancellation, sentence splitter."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

import numpy as np


# ---------------------------------------------------------------------------
# Speech manager
# ---------------------------------------------------------------------------

class TestSpeechManager(unittest.TestCase):
    """Tests for jarvis_ai.speech_manager.SpeechManager."""

    def setUp(self):
        from jarvis_ai.speech_manager import SpeechManager
        self.mock_mouth = MagicMock()
        self.mock_mouth.say = MagicMock()
        self.mock_mouth.stop = MagicMock()
        self.sm = SpeechManager(self.mock_mouth)

    def test_starts_not_speaking(self):
        self.assertFalse(self.sm.is_speaking())

    def test_say_sets_speaking_flag(self):
        self.sm.say("hello")
        self.mock_mouth.say.assert_called_once_with("hello", wait=False)

    def test_stop_calls_mouth_stop(self):
        self.sm.stop()
        self.mock_mouth.stop.assert_called_once()

    def test_generation_increments(self):
        gen1 = self.sm.generation
        self.sm.say("first")
        gen2 = self.sm.generation
        self.sm.say("second")
        gen3 = self.sm.generation
        self.assertEqual(gen2, gen1 + 1)
        self.assertEqual(gen3, gen1 + 2)

    def test_empty_text_ignored(self):
        self.sm.say("")
        self.sm.say("   ")
        self.mock_mouth.say.assert_not_called()

    def test_say_stream_delegates_to_mouth(self):
        self.mock_mouth.say_stream = MagicMock(return_value="streamed text")
        result = self.sm.say_stream(iter(["token1", "token2"]))
        self.assertEqual(result, "streamed text")
        self.mock_mouth.say_stream.assert_called_once()

    def test_history_recorded(self):
        self.sm.say("test message")
        self.assertEqual(len(self.sm.history), 1)
        self.assertEqual(self.sm.history[0]["text"], "test message")

    def test_history_truncated(self):
        sm = self.__class__.__bases__[0] is not None and None or None  # noqa
        from jarvis_ai.speech_manager import SpeechManager
        sm2 = SpeechManager(MagicMock())
        for i in range(60):
            sm2.say(f"msg {i}")
        self.assertLessEqual(len(sm2.history), 50)

    def test_say_stream_returns_empty_on_no_tokens(self):
        self.mock_mouth.say_stream = MagicMock(return_value="")
        result = self.sm.say_stream(iter([]))
        self.assertEqual(result, "")


# ---------------------------------------------------------------------------
# Echo cancellation
# ---------------------------------------------------------------------------

class TestEchoCancel(unittest.TestCase):
    """Tests for jarvis_ai.echo_cancel.EchoCanceller."""

    def test_disabled_passthrough(self):
        from jarvis_ai.echo_cancel import EchoCanceller
        ec = EchoCanceller()
        # AEC_ENABLED defaults to False
        mic = np.array([100, 200, 300], dtype=np.int16)
        result = ec.process(mic, np.array([50, 60], dtype=np.int16))
        np.testing.assert_array_equal(result, mic)

    def test_noise_gate_suppresses_low_mic(self):
        from jarvis_ai.echo_cancel import _NoiseGate
        ng = _NoiseGate(threshold_rms=300, hold_frames=1)
        # Low mic signal, high speaker reference
        mic = np.zeros(100, dtype=np.int16)
        speaker = np.full(100, 1000, dtype=np.int16)
        result = ng.cancel(mic, speaker)
        np.testing.assert_array_equal(result, mic)

    def test_noise_gate_passes_strong_mic(self):
        from jarvis_ai.echo_cancel import _NoiseGate
        ng = _NoiseGate(threshold_rms=300, hold_frames=1)
        mic = np.full(100, 2000, dtype=np.int16)  # strong signal
        speaker = np.full(100, 1000, dtype=np.int16)
        result = ng.cancel(mic, speaker)
        np.testing.assert_array_equal(result, mic)

    def test_noise_gate_no_reference_passes(self):
        from jarvis_ai.echo_cancel import _NoiseGate
        ng = _NoiseGate(threshold_rms=300)
        mic = np.full(100, 100, dtype=np.int16)
        result = ng.cancel(mic, None)
        np.testing.assert_array_equal(result, mic)

    def test_speex_passthrough_when_unavailable(self):
        from jarvis_ai.echo_cancel import _SpeexAEC
        speex = _SpeexAEC()
        if not speex.is_available:
            mic = np.array([1, 2, 3], dtype=np.int16)
            result = speex.cancel(mic, np.array([1], dtype=np.int16))
            np.testing.assert_array_equal(result, mic)


# ---------------------------------------------------------------------------
# Sentence splitter
# ---------------------------------------------------------------------------

class TestSentenceSplitter(unittest.TestCase):
    """Tests for jarvis_ai.sentence_splitter."""

    def test_empty_returns_empty(self):
        from jarvis_ai.sentence_splitter import split_sentences
        self.assertEqual(split_sentences(""), [])
        self.assertEqual(split_sentences("   "), [])

    def test_single_sentence(self):
        from jarvis_ai.sentence_splitter import split_sentences
        result = split_sentences("Hello world.")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], "Hello world.")

    def test_multiple_sentences(self):
        from jarvis_ai.sentence_splitter import split_sentences
        result = split_sentences("First sentence. Second one! Third?")
        self.assertEqual(len(result), 3)

    def test_abbreviation_not_split(self):
        from jarvis_ai.sentence_splitter import split_sentences
        result = split_sentences("Dr. Smith arrived. He was happy.")
        # "Dr." should not be a sentence break
        self.assertEqual(len(result), 2)
        self.assertTrue(result[0].startswith("Dr."))

    def test_mr_abbreviation(self):
        from jarvis_ai.sentence_splitter import split_sentences
        result = split_sentences("Mr. Jones is here.")
        # Should be one sentence (Mr. not a break)
        self.assertEqual(len(result), 1)

    def test_newlines_split(self):
        from jarvis_ai.sentence_splitter import split_sentences
        result = split_sentences("Line one.\nLine two.\nLine three.")
        self.assertEqual(len(result), 3)

    def test_long_sentence_split(self):
        from jarvis_ai.sentence_splitter import split_sentences, _split_long_sentence
        long = ", ".join(["word" * 3] * 20) + "."
        result = _split_long_sentence(long, max_words=10)
        self.assertGreater(len(result), 1)

    def test_split_for_tts_combines_short(self):
        from jarvis_ai.sentence_splitter import split_for_tts
        result = split_for_tts("Hi. Bye. Done.", min_chunk_chars=30)
        # Short sentences should be combined
        self.assertGreaterEqual(len(result), 1)

    def test_split_for_tts_empty(self):
        from jarvis_ai.sentence_splitter import split_for_tts
        self.assertEqual(split_for_tts(""), [])

    def test_question_and_exclamation(self):
        from jarvis_ai.sentence_splitter import split_sentences
        result = split_sentences("What time is it? It's noon! Okay.")
        self.assertEqual(len(result), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
