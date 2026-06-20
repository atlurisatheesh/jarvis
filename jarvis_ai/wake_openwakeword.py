"""openwakeword wake-word engine for Leha.

Uses local neural models — no signup, no API key, fully offline.
Works with Jabra USB headset (clean mic path, bypasses Senary driver).

Wake phrases (built-in models available):
  "hey jarvis"   — model: hey_jarvis
  "alexa"        — model: alexa
  "hey mycroft"  — model: hey_mycroft

Configure in config.py:
  OWW_MODEL_NAME  = "hey_jarvis"   # which phrase to say
  OWW_THRESHOLD   = 0.5            # 0.3=sensitive, 0.7=strict

Install: pip install openwakeword
Models download automatically on first run (~30MB).
"""

import collections
import queue
import math

import numpy as np
import sounddevice as sd

from . import config
from .audio import resolve_device
from scipy.signal import resample_poly


def is_available() -> bool:
    if not getattr(config, "OWW_ENABLED", False):
        return False
    try:
        import openwakeword  # noqa: F401
        return True
    except ImportError:
        return False


def _resample16k(audio: np.ndarray, native: int) -> np.ndarray:
    if native == 16000:
        return audio.astype(np.float32)
    g = math.gcd(native, 16000)
    return resample_poly(audio, 16000 // g, native // g).astype(np.float32)


class OWWListener:
    """openwakeword-based wake detector + VAD command capture in one mic stream.

    Yields:
      None        — wake word detected
      np.ndarray  — 16kHz int16 command audio for Whisper STT
    """

    def __init__(self):
        from openwakeword.model import Model

        model_name = getattr(config, "OWW_MODEL_NAME", "hey_jarvis")
        self._threshold = float(getattr(config, "OWW_THRESHOLD", 0.5))
        self._model_name = model_name
        # Load model; downloads ~30MB on first run
        print(f"[oww] loading model '{model_name}'...", flush=True)
        self._model = Model(wakeword_models=[model_name], inference_framework="onnx")
        print(f"[oww] ready — say '{model_name.replace('_', ' ')}' to wake Leha", flush=True)

    def stream_utterances(
        self,
        should_mute=None,
        silence_ms: int = 900,
        max_seconds: float = 12.0,
        min_samples: int = 6000,
        start_rms: float = 180.0,
    ):
        """Generator — yields None (wake) then np.ndarray (command audio)."""
        dev = resolve_device(config.MIC_DEVICE)
        native = (
            int(sd.query_devices(dev)["default_samplerate"])
            if dev is not None else 16000
        )

        # openwakeword wants ~80ms chunks = 1280 samples at 16kHz
        oww_chunk_16k = 1280
        # Equivalent block size at native rate
        block = max(160, int(native * oww_chunk_16k / 16000))
        chunk_ms = block / native * 1000.0
        silence_need = max(1, int(silence_ms / chunk_ms))
        max_blocks = int(max_seconds * 1000 / chunk_ms)
        wake_timeout_blocks = int(4000 / chunk_ms)

        q_in: queue.Queue = queue.Queue()

        def cb(indata, frames, t, s):
            q_in.put(indata.copy())

        pre: collections.deque = collections.deque(maxlen=3)
        frames_buf: list = []
        started = False
        silent_count = 0
        woken = False
        wait_count = 0

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

                if muted:
                    while not q_in.empty():
                        try:
                            q_in.get_nowait()
                        except Exception:
                            break
                    pre.clear()
                    frames_buf = []
                    started = False
                    silent_count = 0
                    # Keep woken state — barge-in detection after TTS done
                    continue

                if not woken:
                    # --- Wake detection via openwakeword ---
                    chunk16k = _resample16k(raw, native)
                    # openwakeword expects int16 in float range or int16; pass as int16
                    chunk_int16 = np.clip(chunk16k, -32768, 32767).astype(np.int16)
                    preds = self._model.predict(chunk_int16)
                    score = preds.get(self._model_name, 0.0)
                    if score >= self._threshold:
                        print(f"[oww] WAKE WORD DETECTED (score={score:.3f})", flush=True)
                        woken = True
                        wait_count = 0
                        pre.clear()
                        frames_buf = []
                        started = False
                        silent_count = 0
                        yield None
                else:
                    # --- VAD command capture ---
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
                                print("[oww] no speech, re-arming...", flush=True)
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
                                out = _resample16k(audio, native)
                                rv = float(np.sqrt(np.mean(out ** 2))) or 1.0
                                if rv < 500:
                                    out = out * (1500.0 / rv)
                                out = np.clip(out, -32768, 32767).astype(np.int16)
                                if len(out) >= min_samples:
                                    yield out
