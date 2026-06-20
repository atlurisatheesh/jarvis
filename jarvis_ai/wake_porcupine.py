"""Porcupine wake-word engine — far more reliable than Whisper-substring.

Porcupine is a lightweight C library that runs at ~1% CPU and achieves near-100%
wake word accuracy. This replaces the error-prone Whisper substring match.

ONE-TIME SETUP (5 min):
  1. Free account + access key: https://console.picovoice.ai/
  2. Paste key in config.py: PORCUPINE_ACCESS_KEY = "YOUR_KEY_HERE"
  3. Custom "Leha" keyword: console.picovoice.ai -> Wake Word -> train "Leha"
     Download the Windows .ppn file.
     Set PORCUPINE_KEYWORD_PATH = r"D:\\jarvis\\jarvis_ai\\voices\\Leha_en_windows_v3_0_0.ppn"

Without step 3: falls back to built-in "jarvis" keyword (say "Jarvis" to wake).
With step 3: say "Leha" to wake (accurate, near 100%).

Install: pip install pvporcupine
"""

import collections
import math
import queue
import time

import numpy as np
import sounddevice as sd

from . import config
from .audio import resolve_device


def is_available() -> bool:
    """True if pvporcupine installed AND access key configured."""
    try:
        import pvporcupine  # noqa: F401
        return bool(getattr(config, "PORCUPINE_ACCESS_KEY", "").strip())
    except ImportError:
        return False


def _resample(audio: np.ndarray, from_rate: int, to_rate: int) -> np.ndarray:
    """Anti-aliased integer resample (no normalization — Porcupine has own AGC)."""
    if from_rate == to_rate:
        return audio
    from scipy.signal import resample_poly
    g = math.gcd(from_rate, to_rate)
    return resample_poly(audio, to_rate // g, from_rate // g).astype(np.float32)


class PorcupineListener:
    """Combines Porcupine wake detection + VAD command capture in ONE mic stream.

    Yields:
      None        — wake word detected (barge-in: TTS was interrupted)
      np.ndarray  — 16kHz int16 command audio ready for Whisper STT
    """

    def __init__(self):
        import pvporcupine

        key = getattr(config, "PORCUPINE_ACCESS_KEY", "").strip()
        kw_path = getattr(config, "PORCUPINE_KEYWORD_PATH", "").strip()

        if kw_path:
            self._p = pvporcupine.create(access_key=key, keyword_paths=[kw_path])
            print(f"[porcupine] custom keyword: {kw_path}")
        else:
            self._p = pvporcupine.create(access_key=key, keywords=["jarvis"])
            print("[porcupine] using built-in 'jarvis' keyword")
            print("[porcupine] tip: create 'Leha' at console.picovoice.ai -> set PORCUPINE_KEYWORD_PATH")

        self.frame_length = self._p.frame_length  # always 512
        self.sample_rate = self._p.sample_rate    # always 16000
        self._closed = False

    def close(self):
        if not self._closed:
            try:
                self._p.delete()
            except Exception:
                pass
            self._closed = True

    def __del__(self):
        self.close()

    def stream_utterances(
        self,
        should_mute=None,
        silence_ms: int = 900,
        max_seconds: float = 12.0,
        min_samples: int = 6000,
        start_rms: float = 180.0,
    ):
        """Generator — keep calling next() until KeyboardInterrupt.

        Porcupine runs at ALL times (even during TTS) for barge-in support.
        VAD command capture runs only when woken and TTS is silent.
        """
        dev = resolve_device(config.MIC_DEVICE)
        native = (
            int(sd.query_devices(dev)["default_samplerate"])
            if dev is not None
            else 16000
        )

        # Block size: smallest of ~32ms (fine for Porcupine frames) and ~50ms (VAD)
        block = max(160, int(native * 0.032))
        chunk_ms = block / native * 1000.0
        silence_need = max(1, int(silence_ms / chunk_ms))
        max_blocks = int(max_seconds * 1000 / chunk_ms)
        # Frames to wait for speech onset before giving up and re-arming wake
        wake_timeout_blocks = int(4000 / chunk_ms)

        q_in: queue.Queue = queue.Queue()

        def cb(indata, frames, t, s):
            q_in.put(indata.copy())

        # Porcupine accumulator (native → 16k resample buffer)
        porc_acc: list = []
        porc_acc_n = 0
        # How many native samples equal one Porcupine frame at 16kHz
        porc_frame_native = int(native * self.frame_length / self.sample_rate)

        # VAD state
        pre: collections.deque = collections.deque(maxlen=3)
        frames_buf: list = []
        started = False
        silent_count = 0
        woken = False
        wait_count = 0  # blocks since wake with no speech (for timeout)

        with sd.InputStream(
            samplerate=native,
            channels=1,
            blocksize=block,
            dtype="int16",
            device=dev,
            callback=cb,
        ):
            while True:
                raw = q_in.get().flatten().astype(np.float32)
                muted = bool(should_mute and should_mute())

                # --- Always run Porcupine (even during TTS for barge-in) ---
                porc_acc.append(raw)
                porc_acc_n += len(raw)

                if porc_acc_n >= porc_frame_native:
                    accumulated = np.concatenate(porc_acc)
                    porc_acc = []
                    porc_acc_n = 0

                    resampled = _resample(accumulated, native, self.sample_rate)
                    # Process as many complete frames as available
                    idx = 0
                    while idx + self.frame_length <= len(resampled):
                        frame = resampled[idx:idx + self.frame_length].astype(np.int16).tolist()
                        result = self._p.process(frame)
                        if result >= 0:
                            print("[porcupine] WAKE WORD DETECTED!", flush=True)
                            # Reset VAD state
                            pre.clear()
                            frames_buf = []
                            started = False
                            silent_count = 0
                            wait_count = 0
                            woken = True
                            yield None  # caller: interrupt TTS, play earcon, say "Yes Sir?"
                            break
                        idx += self.frame_length

                # --- VAD command capture (only when woken and mic not muted) ---
                if muted:
                    # During TTS: drain queue, reset VAD so stale frames don't bleed
                    while not q_in.empty():
                        try:
                            q_in.get_nowait()
                        except Exception:
                            break
                    pre.clear()
                    frames_buf = []
                    started = False
                    silent_count = 0
                    # Don't reset woken — Porcupine barge-in should re-arm after TTS
                    continue

                if not woken:
                    continue

                rms = float(np.sqrt(np.mean(raw ** 2)))
                if not started:
                    pre.append(raw)
                    if rms > start_rms:
                        frames_buf.extend(pre)
                        pre.clear()
                        started, silent_count, wait_count = True, 0, 0
                    else:
                        wait_count += 1
                        if wait_count >= wake_timeout_blocks:
                            # 4s of silence after wake → go back to detection mode
                            print("[porcupine] no speech after wake, re-arming...", flush=True)
                            woken = False
                            pre.clear()
                            wait_count = 0
                else:
                    frames_buf.append(raw)
                    if rms > start_rms:
                        silent_count = 0
                    else:
                        silent_count += 1
                        if silent_count >= silence_need or len(frames_buf) >= max_blocks:
                            audio = np.concatenate(frames_buf)
                            frames_buf = []
                            started = False
                            silent_count = 0
                            woken = False

                            # Resample + gentle normalize for Whisper
                            if native != 16000:
                                audio = _resample(audio, native, 16000)
                            rms_val = float(np.sqrt(np.mean(audio ** 2))) or 1.0
                            if rms_val < 500:
                                audio = audio * (1500.0 / rms_val)
                            audio = np.clip(audio, -32768, 32767).astype(np.int16)

                            if len(audio) >= min_samples:
                                yield audio
