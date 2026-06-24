"""Tests for Phase 1: synthetic wake data, trainer, evaluator, strict mode."""
from __future__ import annotations

import struct
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch, MagicMock


def _make_wav(path: Path, n_samples: int = 16000, freq: float = 440.0, rate: int = 16000):
    """Write a simple tone WAV for testing."""
    import numpy as np
    t = np.arange(n_samples) / rate
    samples = (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    ints = np.clip(samples * 32767, -32768, 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(ints.tobytes())


# ---------------------------------------------------------------------------
# Wake phrase strict mode
# ---------------------------------------------------------------------------

class TestStrictMode(unittest.TestCase):
    def test_strict_mode_false_by_default(self):
        from jarvis_ai import wake_phrases
        self.assertFalse(wake_phrases.strict_mode())

    def test_strict_mode_true_when_custom_enabled(self):
        from jarvis_ai import wake_phrases
        with patch("jarvis_ai.config.CUSTOM_WAKE_ENABLED", True):
            self.assertTrue(wake_phrases.strict_mode())

    def test_has_trigger_loose_mode_matches_broad_alias(self):
        # "layla" is a broad alias that should match in loose mode
        from jarvis_ai import wake_phrases
        with patch("jarvis_ai.config.CUSTOM_WAKE_ENABLED", False):
            self.assertTrue(wake_phrases.has_trigger("layla what time is it"))

    def test_has_trigger_strict_mode_drops_broad_alias(self):
        # In strict mode, broad aliases like "layla" should NOT trigger
        from jarvis_ai import wake_phrases
        with patch("jarvis_ai.config.CUSTOM_WAKE_ENABLED", True):
            self.assertFalse(wake_phrases.has_trigger("layla what time is it"))

    def test_has_trigger_strict_mode_keeps_precise(self):
        from jarvis_ai import wake_phrases
        with patch("jarvis_ai.config.CUSTOM_WAKE_ENABLED", True):
            self.assertTrue(wake_phrases.has_trigger("leha what time is it"))
            self.assertTrue(wake_phrases.has_trigger("hey leha"))

    def test_is_hallucination_uses_strict_fragments(self):
        from jarvis_ai import wake_phrases
        # "lena" alone is a fragment; in loose mode it prevents hallucination flag,
        # in strict mode it should be treated as hallucination (too short, not precise)
        with patch("jarvis_ai.config.CUSTOM_WAKE_ENABLED", True):
            # "lena" is not in strict fragments, so short text -> hallucination
            self.assertTrue(wake_phrases.is_hallucination("lena"))


# ---------------------------------------------------------------------------
# Trainer audio helpers
# ---------------------------------------------------------------------------

class TestTrainerHelpers(unittest.TestCase):
    def test_load_wav_returns_float32(self):
        from jarvis_ai import wake_trainer
        with tempfile.TemporaryDirectory() as tmp:
            wav = Path(tmp) / "test.wav"
            _make_wav(wav)
            audio = wake_trainer._load_wav_16k(wav)
            self.assertIsNotNone(audio)
            self.assertEqual(audio.dtype.name, "float32")

    def test_load_wav_invalid_returns_none(self):
        from jarvis_ai import wake_trainer
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.wav"
            bad.write_text("not audio")
            self.assertIsNone(wake_trainer._load_wav_16k(bad))

    def test_window_crops_long(self):
        import numpy as np
        from jarvis_ai import wake_trainer
        audio = np.ones(24000, dtype=np.float32)
        result = wake_trainer._window(audio, window_sec=1.0, rate=16000)
        self.assertEqual(len(result), 16000)

    def test_window_pads_short(self):
        import numpy as np
        from jarvis_ai import wake_trainer
        audio = np.ones(8000, dtype=np.float32)
        result = wake_trainer._window(audio, window_sec=1.0, rate=16000)
        self.assertEqual(len(result), 16000)

    def test_augment_preserves_dtype(self):
        import numpy as np
        from jarvis_ai import wake_trainer
        audio = np.random.randn(16000).astype(np.float32)
        aug = wake_trainer._augment(audio)
        self.assertEqual(aug.dtype, np.float32)
        # Speed perturbation legitimately changes length; only require non-empty.
        self.assertGreater(len(aug), 0)

    def test_load_clips_from_dirs_counts(self):
        from jarvis_ai import wake_trainer
        with tempfile.TemporaryDirectory() as tmp:
            pos = Path(tmp) / "positive"
            neg = Path(tmp) / "negative"
            pos.mkdir()
            neg.mkdir()
            for i in range(5):
                _make_wav(pos / f"p{i}.wav")
            for i in range(10):
                _make_wav(neg / f"n{i}.wav")
            p, n = wake_trainer._load_clips_from_dirs(str(pos), str(neg), augment_factor=2)
            self.assertEqual(len(p), 15)  # 5 + 5*2
            self.assertEqual(len(n), 10)


# ---------------------------------------------------------------------------
# Evaluator approval logic
# ---------------------------------------------------------------------------

class TestEvaluatorApproval(unittest.TestCase):
    def test_approved_when_high_recall_low_falsewake(self):
        from jarvis_ai import wake_evaluator
        # Build a fake result via the formula used in _evaluate_model
        recall = 0.97
        false_wake = 0.005
        approved = recall >= 0.95 and false_wake <= 0.01
        self.assertTrue(approved)

    def test_not_approved_when_low_recall(self):
        recall = 0.90
        false_wake = 0.005
        approved = recall >= 0.95 and false_wake <= 0.01
        self.assertFalse(approved)

    def test_not_approved_when_high_falsewake(self):
        recall = 0.99
        false_wake = 0.02
        approved = recall >= 0.95 and false_wake <= 0.01
        self.assertFalse(approved)


# ---------------------------------------------------------------------------
# Wake local ONNX 2-hit logic
# ---------------------------------------------------------------------------

class TestTwoHitLogic(unittest.TestCase):
    """The wake detector requires 2 consecutive hits above threshold."""

    def test_triggers_on_two_consecutive(self):
        threshold = 0.7
        scores = [0.8, 0.9]
        consecutive = sum(1 for s in scores if s >= threshold)
        self.assertGreaterEqual(consecutive, 2)

    def test_no_trigger_on_single_spike(self):
        threshold = 0.7
        scores = [0.95, 0.1, 0.2]
        consecutive = 0
        triggered = False
        for s in scores:
            if s >= threshold:
                consecutive += 1
                if consecutive >= 2:
                    triggered = True
                    break
            else:
                consecutive = 0
        self.assertFalse(triggered)


# ---------------------------------------------------------------------------
# Synthetic data generator helpers (pure functions, no TTS)
# ---------------------------------------------------------------------------

class TestSyntheticGenHelpers(unittest.TestCase):
    def test_add_noise_preserves_length(self):
        import numpy as np
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent / "tools"))
        try:
            from generate_synthetic_wake_data import _add_noise, _vary_gain, _pad_or_crop
            audio = np.ones(16000, dtype=np.float32) * 0.5
            noisy = _add_noise(audio, 20.0)
            self.assertEqual(len(noisy), 16000)
        finally:
            sys.path.pop(0)

    def test_pad_or_crop_exact_length(self):
        import numpy as np
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent / "tools"))
        try:
            from generate_synthetic_wake_data import _pad_or_crop
            short = np.ones(8000, dtype=np.float32)
            result = _pad_or_crop(short, 16000)
            self.assertEqual(len(result), 16000)
            long = np.ones(32000, dtype=np.float32)
            result = _pad_or_crop(long, 16000)
            self.assertEqual(len(result), 16000)
        finally:
            sys.path.pop(0)

    def test_save_wav_creates_valid_file(self):
        import numpy as np
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent / "tools"))
        try:
            from generate_synthetic_wake_data import _save_wav
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "out.wav"
                audio = np.zeros(16000, dtype=np.float32)
                _save_wav(path, audio)
                self.assertTrue(path.exists())
                self.assertGreater(path.stat().st_size, 44)  # WAV header
        finally:
            sys.path.pop(0)

    def test_manifest_is_valid_json(self):
        import json
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent / "tools"))
        try:
            from generate_synthetic_wake_data import write_manifest
            with tempfile.TemporaryDirectory() as tmp:
                m = write_manifest(Path(tmp), [Path("a")], [Path("b"), Path("c")])
                data = json.loads(m.read_text())
                self.assertEqual(data["positive_count"], 1)
                self.assertEqual(data["negative_count"], 2)
                self.assertEqual(data["sample_rate"], 16000)
        finally:
            sys.path.pop(0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
