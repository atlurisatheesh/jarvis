"""Tiny optional speaker profile for owner-gating sensitive commands.

This is not bank-grade biometrics. It is a lightweight voice similarity check
using spectral features already available from numpy/scipy, good enough to
reduce accidental commands from another nearby speaker.
"""
import json
from pathlib import Path

import numpy as np
from scipy.fft import rfft

from . import config

PROFILE_PATH = config.MEMORY_DIR / "speaker_profile.json"


def _frame_features(audio_int16: np.ndarray, sample_rate: int = 16000) -> np.ndarray:
    audio = audio_int16.astype(np.float32).flatten()
    if len(audio) < sample_rate // 2:
        return np.zeros(24, dtype=np.float32)
    audio = audio - float(np.mean(audio))
    rms = float(np.sqrt(np.mean(audio ** 2))) or 1.0
    audio = audio / rms

    frame = int(sample_rate * 0.08)
    hop = int(sample_rate * 0.04)
    feats = []
    for start in range(0, max(1, len(audio) - frame), hop):
        chunk = audio[start:start + frame]
        if len(chunk) < frame:
            break
        windowed = chunk * np.hanning(len(chunk))
        spectrum = np.abs(rfft(windowed)) + 1e-6
        bands = np.array_split(np.log(spectrum), 24)
        feats.append([float(np.mean(b)) for b in bands])
    if not feats:
        return np.zeros(24, dtype=np.float32)
    return np.mean(np.array(feats, dtype=np.float32), axis=0)


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = (float(np.linalg.norm(a)) * float(np.linalg.norm(b))) or 1.0
    return float(np.dot(a, b) / denom)


def enroll(audio_int16: np.ndarray) -> str:
    config.MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    feature = _frame_features(audio_int16)
    PROFILE_PATH.write_text(
        json.dumps({"feature": feature.tolist()}, indent=2),
        encoding="utf-8",
    )
    return "Voice trained, Sir."


def has_profile() -> bool:
    return PROFILE_PATH.exists()


def verify(audio_int16: np.ndarray, threshold: float | None = None) -> tuple[bool, float]:
    if threshold is None:
        threshold = config.SPEAKER_VERIFY_THRESHOLD
    if not PROFILE_PATH.exists():
        return True, 1.0
    try:
        saved = np.array(json.loads(PROFILE_PATH.read_text(encoding="utf-8"))["feature"], dtype=np.float32)
    except Exception:
        return True, 1.0
    score = _cosine(_frame_features(audio_int16), saved)
    return score >= threshold, score
