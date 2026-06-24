"""Generate synthetic wake-word training data using Edge TTS.

Phase 1 helper. Produces synthetic positive clips (the wake word "Leha" spoken
in many phrasings) and synthetic negative clips (common conversational words,
similar-sounding distractors, and near-misses) so a wake model can be trained
and evaluated *before* the owner records real voice samples.

This is intentionally a stepping stone, not a replacement for real recordings:
- Real recordings from the actual owner give the best wake accuracy.
- Synthetic Edge-TTS clips are a different speaker, so a model trained only on
  them will generalise to *any* speaker, not just the owner. That is fine for
  getting the pipeline working and for an initial smoke-test model, but the
  roadmap recommends re-training with real owner clips later.

The generated clips are 16 kHz mono WAV, ~0.8-1.5 s each, matching what
``jarvis_ai.wake_trainer`` and ``jarvis_ai.wake_evaluator`` expect.

Usage::

    python tools/generate_synthetic_wake_data.py --out voices/wake_synthetic
    python tools/generate_synthetic_wake_data.py --out voices/wake_synthetic --positives 200 --negatives 2000
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import struct
import wave
from pathlib import Path

import numpy as np

RATE = 16000

# Positive phrasings — the wake word "Leha" in natural call patterns.
POSITIVE_PHRASINGS = [
    "Leha",
    "Hey Leha",
    "Leha, listen",
    "Leha, can you hear me",
    "OK Leha",
    "Leha, are you there",
    "Hi Leha",
    "Leha, help me",
    "Yo Leha",
    "Leha, what time is it",
]

# Negative distractors — words/phrases that sound similar to "Leha" or are
# common background speech. A good wake model must reject ALL of these.
# Deliberately includes near-misses so the model learns the *exact* phonemes.
NEGATIVE_PHRASINGS = [
    # Near-sounding distractors (false-wake bait)
    "leader", "lead", "leaf", "leave", "leaving", "leaping", "leap",
    "lava", "lila", "lily", "lisa", "layla", "lena", "laura", "lola",
    "later", "latter", "liter", "lethal", "level", "legal", "lemon",
    "the la", "she la", "see la", "lee ha", "lay ha",
    # Common background conversation
    "hello", "hey there", "how are you", "what is that", "I don't know",
    "let me check", "can you help", "open the door", "turn on the light",
    "what is the weather", "set a timer", "play some music", "good morning",
    "good night", "see you later", "talk to you soon", "thank you very much",
    "yes please", "no thank you", "excuse me", "sorry about that",
    # Other assistant names (must not cross-trigger)
    "alexa", "hey alexa", "siri", "hey siri", "google", "hey google",
    "jarvis", "hey jarvis", "computer", "hey computer",
    # Silence-ish / filler
    "uh", "um", "hmm", "okay", "alright", "so", "well", "like",
]

NEGATIVE_VARIATIONS = [
    "{w}", "the word {w}", "say {w}", "{w} again", "no {w}", "yes {w}",
]


def _save_wav(path: Path, audio: np.ndarray, rate: int = RATE) -> None:
    """Write a float32/float array in [-1,1] as a 16-bit PCM WAV."""
    ints = np.clip(audio * 32767, -32768, 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(ints.tobytes())


async def _tts_to_array(text: str, voice: str, rate_str: str) -> np.ndarray:
    """Synthesize *text* via edge-tts, return float32 mono at RATE."""
    import edge_tts
    import tempfile
    import os
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        tmp = f.name
    try:
        communicate = edge_tts.Communicate(text, voice, rate=rate_str)
        await communicate.save(tmp)
        import soundfile as sf
        data, sr = sf.read(tmp, dtype="float32")
        if data.ndim > 1:
            data = data[:, 0]
        if sr != RATE:
            from scipy.signal import resample_poly
            g = np.gcd(sr, RATE)
            data = resample_poly(data, RATE // g, sr // g)
        peak = float(np.max(np.abs(data))) or 1.0
        return data / peak
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _add_noise(audio: np.ndarray, snr_db: float) -> np.ndarray:
    """Mix white noise at the given SNR (dB). snr_db=inf means no noise."""
    if not np.isfinite(snr_db):
        return audio
    signal_power = float(np.mean(audio ** 2)) or 1e-6
    noise_power = signal_power / (10 ** (snr_db / 10))
    noise = np.random.randn(len(audio)).astype(np.float32) * (noise_power ** 0.5)
    return audio + noise


def _vary_gain(audio: np.ndarray, lo: float = 0.6, hi: float = 1.0) -> np.ndarray:
    return audio * random.uniform(lo, hi)


def _vary_speed(audio: np.ndarray, rate: int = RATE) -> np.ndarray:
    factor = random.uniform(0.9, 1.1)
    from scipy.signal import resample_poly
    new_len = int(len(audio) / factor)
    g = np.gcd(new_len, len(audio)) or 1
    return resample_poly(audio, new_len // g, len(audio) // g).astype(np.float32)


def _pad_or_crop(audio: np.ndarray, target_samples: int) -> np.ndarray:
    if len(audio) >= target_samples:
        start = (len(audio) - target_samples) // 2
        return audio[start:start + target_samples]
    out = np.zeros(target_samples, dtype=np.float32)
    start = (target_samples - len(audio)) // 2
    out[start:start + len(audio)] = audio
    return out


async def generate_positive(out_dir: Path, count: int, voice: str) -> list[Path]:
    """Generate *count* synthetic positive clips (wake word)."""
    pos_dir = out_dir / "positive"
    pos_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    # Multiple voices give speaker diversity so the model doesn't overfit one TTS voice.
    voices = [voice, "en-US-GuyNeural", "en-US-AriaNeural", "en-GB-RyanNeural"]
    for i in range(count):
        phrase = random.choice(POSITIVE_PHRASINGS)
        v = random.choice(voices)
        rate_str = random.choice(["-10%", "-5%", "+0%", "+5%", "+10%"])
        try:
            audio = await _tts_to_array(phrase, v, rate_str)
        except Exception as e:
            print(f"[gen] positive {i} failed ({phrase}): {e}")
            continue
        # Augment: room noise, gain, speed
        audio = _vary_speed(audio)
        audio = _add_noise(audio, random.choice([40.0, 30.0, 25.0, 20.0, float("inf")]))
        audio = _vary_gain(audio)
        audio = _pad_or_crop(audio, RATE)  # exactly 1 second
        path = pos_dir / f"pos_{i:04d}.wav"
        _save_wav(path, audio)
        paths.append(path)
    return paths


async def generate_negative(out_dir: Path, count: int, voice: str) -> list[Path]:
    """Generate *count* synthetic negative clips (non-wake speech)."""
    neg_dir = out_dir / "negative"
    neg_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    voices = [voice, "en-US-GuyNeural", "en-US-AriaNeural", "en-GB-RyanNeural",
              "en-US-DavisNeural", "en-IN-PrabhatNeural"]
    for i in range(count):
        word = random.choice(NEGATIVE_PHRASINGS)
        template = random.choice(NEGATIVE_VARIATIONS)
        phrase = template.format(w=word) if "{" in template else word
        v = random.choice(voices)
        rate_str = random.choice(["-5%", "+0%", "+5%"])
        try:
            audio = await _tts_to_array(phrase, v, rate_str)
        except Exception as e:
            print(f"[gen] negative {i} failed ({phrase}): {e}")
            continue
        audio = _vary_speed(audio)
        audio = _add_noise(audio, random.choice([35.0, 25.0, 20.0, 15.0, float("inf")]))
        audio = _vary_gain(audio)
        audio = _pad_or_crop(audio, RATE)
        path = neg_dir / f"neg_{i:05d}.wav"
        _save_wav(path, audio)
        paths.append(path)
    return paths


def write_manifest(out_dir: Path, pos_paths: list[Path], neg_paths: list[Path]) -> Path:
    """Write a manifest.json describing the dataset (consumed by trainer/evaluator)."""
    manifest = {
        "format": "leha-wake-synthetic-v1",
        "sample_rate": RATE,
        "duration_seconds": 1.0,
        "positive_count": len(pos_paths),
        "negative_count": len(neg_paths),
        "positive_dir": str(out_dir / "positive"),
        "negative_dir": str(out_dir / "negative"),
        "note": (
            "Synthetic Edge-TTS data. Good for pipeline smoke tests. "
            "Re-train with real owner recordings for production accuracy."
        ),
    }
    path = out_dir / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return path


async def run(out_dir: Path, positives: int, negatives: int, voice: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[gen] generating {positives} positive + {negatives} negative clips -> {out_dir}")
    pos = await generate_positive(out_dir, positives, voice)
    neg = await generate_negative(out_dir, negatives, voice)
    manifest = write_manifest(out_dir, pos, neg)
    print(f"[gen] done: {len(pos)} positive, {len(neg)} negative clips")
    print(f"[gen] manifest: {manifest}")


def main():
    parser = argparse.ArgumentParser(description="Generate synthetic Leha wake-word data")
    parser.add_argument("--out", default="voices/wake_synthetic", help="Output directory")
    parser.add_argument("--positives", type=int, default=200, help="Number of positive clips")
    parser.add_argument("--negatives", type=int, default=2000, help="Number of negative clips")
    parser.add_argument("--voice", default="en-IN-NeerjaNeural", help="Primary edge-tts voice")
    args = parser.parse_args()
    asyncio.run(run(Path(args.out), args.positives, args.negatives, args.voice))


if __name__ == "__main__":
    main()
