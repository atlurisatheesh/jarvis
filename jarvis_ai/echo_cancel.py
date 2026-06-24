"""Acoustic echo cancellation (AEC) for barge-in support.

Two strategies:
    1. **Software AEC** via ``speexdsp`` — removes speaker output from the mic
       signal so Leha can hear the wake word while it is speaking.
    2. **Noise-gate fallback** — if ``speexdsp`` is unavailable, a simple RMS
       noise gate is used.  This does NOT enable true barge-in but prevents
       feedback loops.

Hardware AEC headsets can be configured via ``config.AEC_HARDWARE_DEVICE``.
When a hardware AEC device is selected, this module becomes a passthrough.
"""
from __future__ import annotations

import collections
import math

import numpy as np

from . import config


# ---------------------------------------------------------------------------
# SpeexDSP echo canceller
# ---------------------------------------------------------------------------

class _SpeexAEC:
    """Wrapper around ``speexdsp.EchoCanceller``.

    ``speexdsp`` is optional.  If not installed, ``is_available`` returns False.
    """

    def __init__(self, frame_size: int = 1600, sample_rate: int = 16000, filter_length: int = 16000):
        self._frame_size = frame_size
        self._sample_rate = sample_rate
        self._filter_length = filter_length
        self._canceller = None
        try:
            from speexdsp import EchoCanceller
            self._canceller = EchoCanceller(
                frame_size=frame_size,
                filter_length=filter_length,
                sample_rate=sample_rate,
            )
        except (ImportError, Exception):
            self._canceller = None

    @property
    def is_available(self) -> bool:
        return self._canceller is not None

    def cancel(self, mic_audio: np.ndarray, speaker_audio: np.ndarray | None) -> np.ndarray:
        """Cancel speaker echo from mic audio.

        ``speaker_audio`` is the reference signal (what was played on the
        speaker).  Returns the cleaned mic signal.
        """
        if self._canceller is None or speaker_audio is None:
            return mic_audio
        try:
            mic_bytes = mic_audio.astype(np.int16).tobytes()
            ref_bytes = speaker_audio.astype(np.int16).tobytes()
            # Pad/truncate reference to match mic length
            if len(ref_bytes) < len(mic_bytes):
                ref_bytes = ref_bytes.ljust(len(mic_bytes), b"\x00")
            elif len(ref_bytes) > len(mic_bytes):
                ref_bytes = ref_bytes[: len(mic_bytes)]
            cleaned = self._canceller.echo_cancel(mic_bytes, ref_bytes)
            return np.frombuffer(cleaned, dtype=np.int16).astype(mic_audio.dtype)
        except Exception:
            return mic_audio


# ---------------------------------------------------------------------------
# Noise-gate fallback
# ---------------------------------------------------------------------------

class _NoiseGate:
    """Simple RMS noise gate — not true AEC, but prevents feedback."""

    def __init__(self, threshold_rms: float = 300.0, hold_frames: int = 3):
        self._threshold = threshold_rms
        self._hold = hold_frames
        self._silence_count = 0

    def cancel(self, mic_audio: np.ndarray, speaker_audio: np.ndarray | None) -> np.ndarray:
        """Gate the mic signal when a speaker reference is present."""
        if speaker_audio is None:
            return mic_audio
        # If speaker is active and mic signal is low, suppress it
        ref_rms = float(np.sqrt(np.mean(speaker_audio.astype(np.float64) ** 2)))
        mic_rms = float(np.sqrt(np.mean(mic_audio.astype(np.float64) ** 2)))
        if ref_rms > self._threshold * 0.5 and mic_rms < ref_rms:
            self._silence_count += 1
            if self._silence_count >= self._hold:
                return np.zeros_like(mic_audio)
        else:
            self._silence_count = 0
        return mic_audio


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

class EchoCanceller:
    """Unified AEC interface.  Picks the best available strategy."""

    def __init__(self):
        self._enabled = getattr(config, "AEC_ENABLED", False)
        self._lib = getattr(config, "AEC_LIBRARY", "speexdsp")
        self._hw_device = getattr(config, "AEC_HARDWARE_DEVICE", None)
        self._impl: _SpeexAEC | _NoiseGate | None = None

        if not self._enabled:
            return

        if self._hw_device is not None:
            # Hardware AEC — passthrough, no software processing
            print(f"[aec] hardware AEC device configured: {self._hw_device}")
            self._impl = None
            return

        if self._lib == "speexdsp":
            speex = _SpeexAEC()
            if speex.is_available:
                print("[aec] using SpeexDSP software echo cancellation")
                self._impl = speex
            else:
                print("[aec] speexdsp not available; falling back to noise gate")
                self._impl = _NoiseGate()
        else:
            self._impl = _NoiseGate()

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def is_hardware(self) -> bool:
        return self._hw_device is not None

    @property
    def active(self) -> bool:
        """True if any AEC processing is active (software or hardware)."""
        return self._enabled and (self._impl is not None or self.is_hardware)

    def process(self, mic_audio: np.ndarray, speaker_audio: np.ndarray | None) -> np.ndarray:
        """Cancel echo from mic audio using the speaker reference."""
        if not self._enabled or self._impl is None:
            return mic_audio
        return self._impl.cancel(mic_audio, speaker_audio)
