"""Private locally trained ONNX wake detector for the phrase "Leha".

Supports configurable cooldown, confidence logging to file, and runtime
state tracking.  The detector requires two consecutive ONNX scores above
the threshold before triggering (anti-false-positive).
"""

from __future__ import annotations

import collections
import math
import os
import queue
import time

import numpy as np
import sounddevice as sd
from scipy.signal import resample_poly

from . import config
from .audio import _capture_rates, resolve_device


RATE = 16_000
WINDOW = RATE


def is_available() -> bool:
    if not getattr(config, "CUSTOM_WAKE_ENABLED", False):
        return False
    path = getattr(config, "CUSTOM_WAKE_MODEL_PATH", "").strip()
    if not path or not os.path.isfile(path):
        return False
    try:
        import onnxruntime  # noqa: F401
        return True
    except ImportError:
        return False


def _resample(audio: np.ndarray, native: int) -> np.ndarray:
    if native == RATE:
        return audio.astype(np.float32)
    divisor = math.gcd(native, RATE)
    return resample_poly(audio, RATE // divisor, native // divisor).astype(np.float32)


class LocalOnnxWakeListener:
    """One microphone stream: local wake detection followed by command capture.

    Parameters consumed from *config*:
        CUSTOM_WAKE_MODEL_PATH  – path to the ONNX model file
        CUSTOM_WAKE_THRESHOLD   – sigmoid threshold (default 0.995)
        WAKE_COOLDOWN_SECONDS   – seconds to suppress re-detection after wake
        WAKE_CONFIDENCE_LOG     – optional file path for per-window score log
    """

    def __init__(self):
        import onnxruntime as ort

        path = config.CUSTOM_WAKE_MODEL_PATH
        self._session = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
        self._input = self._session.get_inputs()[0].name
        self._threshold = float(getattr(config, "CUSTOM_WAKE_THRESHOLD", 0.92))
        self._cooldown_sec = float(getattr(config, "WAKE_COOLDOWN_SECONDS", 4))
        self._conf_log_path = getattr(config, "WAKE_CONFIDENCE_LOG", "").strip()
        self._score_count = 0
        self._last_wake_score = 0.0
        print(f"[wake/local] loaded private Leha model: {path}  "
              f"threshold={self._threshold}  cooldown={self._cooldown_sec}s", flush=True)

    # -- public accessors used by listen.py / dashboard --------------------

    @property
    def last_wake_score(self) -> float:
        """Sigmoid score of the most recent wake trigger."""
        return self._last_wake_score

    @property
    def score_count(self) -> int:
        """Total number of windows scored since start."""
        return self._score_count

    # -----------------------------------------------------------------------

    def _score(self, audio: np.ndarray) -> float:
        value = self._session.run(None, {self._input: audio[None, None, :].astype(np.float32)})[0]
        logit = float(np.asarray(value).reshape(-1)[0])
        prob = 1.0 / (1.0 + math.exp(-logit))
        self._score_count += 1
        return prob

    def _log_confidence(self, score: float, woken: bool):
        """Append a confidence log line when a log path is configured."""
        path = self._conf_log_path
        if not path:
            return
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%H:%M:%S')}  score={score:.4f}  "
                        f"woken={'1' if woken else '0'}  n={self._score_count}\n")
        except OSError:
            pass

    def stream_utterances(
        self,
        should_mute=None,
        silence_ms: int = 900,
        max_seconds: float = 12.0,
        min_samples: int = 6000,
        start_rms: float = 180.0,
    ):
        dev = resolve_device(config.MIC_DEVICE)
        last_error = None
        for native in _capture_rates(dev):
            block = max(160, int(native * 0.10))
            chunk_ms = block / native * 1000.0
            silence_need = max(1, int(silence_ms / chunk_ms))
            max_blocks = int(max_seconds * 1000 / chunk_ms)
            wake_timeout = int(4000 / chunk_ms)
            incoming: queue.Queue = queue.Queue()

            def callback(indata, frames, timing, status):
                incoming.put(indata.copy())

            try:
                stream = sd.InputStream(
                    samplerate=native, channels=1, blocksize=block, dtype="int16",
                    device=dev, callback=callback,
                )
                stream.start()
            except Exception as exc:
                last_error = exc
                continue

            print(f"[wake/local] listening at {native} Hz", flush=True)
            rolling = np.zeros(0, dtype=np.float32)
            pre: collections.deque = collections.deque(maxlen=3)
            command: list[np.ndarray] = []
            woken = started = False
            silent = wait = hits = 0
            # The startup greeting contains the word "Leha". Let it and its
            # speaker echo clear before evaluating the first rolling window.
            cooldown_until = time.monotonic() + 5.0
            discard_after_wake = False
            try:
                while True:
                    raw = incoming.get().flatten().astype(np.float32)
                    if discard_after_wake:
                        # The generator pauses while Leha says "Ready.". Drop
                        # those queued speaker frames before hearing the command.
                        while not incoming.empty():
                            try:
                                incoming.get_nowait()
                            except queue.Empty:
                                break
                        discard_after_wake = False
                        continue
                    if should_mute and should_mute():
                        rolling = np.zeros(0, dtype=np.float32)
                        pre.clear(); command = []; woken = started = False
                        silent = wait = hits = 0
                        continue

                    if not woken:
                        rolling = np.concatenate((rolling, _resample(raw, native) / 32768.0))[-WINDOW:]
                        if len(rolling) < WINDOW:
                            continue
                        if time.monotonic() < cooldown_until:
                            hits = 0
                            continue
                        score = self._score(rolling)
                        self._log_confidence(score, woken=False)
                        hits = hits + 1 if score >= self._threshold else 0
                        if hits >= 2:
                            self._last_wake_score = score
                            self._log_confidence(score, woken=True)
                            print(f"[wake/local] Leha detected (score={score:.3f})", flush=True)
                            rolling = np.zeros(0, dtype=np.float32)
                            pre.clear(); command = []; woken = True
                            started = False; silent = wait = hits = 0
                            # Give the activation sound and any speaker echo time
                            # to leave the microphone before re-arming detection.
                            cooldown_until = time.monotonic() + self._cooldown_sec
                            discard_after_wake = True
                            yield None
                        continue

                    rms = float(np.sqrt(np.mean(raw ** 2)))
                    if not started:
                        pre.append(raw)
                        if rms > start_rms:
                            command.extend(pre); pre.clear(); started = True; silent = wait = 0
                        else:
                            wait += 1
                            if wait >= wake_timeout:
                                woken = False; pre.clear(); wait = 0
                    else:
                        command.append(raw)
                        if rms > start_rms:
                            silent = 0
                        else:
                            silent += 1
                            if silent >= silence_need or len(command) >= max_blocks:
                                audio = _resample(np.concatenate(command), native)
                                command = []; woken = started = False; silent = 0
                                if len(audio) >= min_samples:
                                    yield np.clip(audio, -32768, 32767).astype(np.int16)
            finally:
                stream.stop(); stream.close()
        raise RuntimeError(f"Could not open microphone: {last_error}")
