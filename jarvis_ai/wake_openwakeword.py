"""openwakeword wake-word engine for Leha.

Uses local neural models — no signup, no API key, fully offline.
Works with Jabra USB headset (clean mic path, bypasses Senary driver).

Supports loading MULTIPLE wake models simultaneously — any one firing wakes Leha.
This lets you say either "leha" or "hey leha" (custom trained models), or fall
back to the built-in "hey jarvis" / "alexa" / "hey mycroft" models.

Configure in config.py:
  OWW_ENABLED       = True                   # master switch
  OWW_CUSTOM_MODELS = [                      # trained .onnx files (highest priority)
      "voices/leha.onnx",
      "voices/hey_leha.onnx",
  ]
  OWW_MODEL_PATH    = ""                     # single custom path (legacy, overrides name)
  OWW_MODEL_NAME    = "hey_jarvis"           # built-in fallback (when no custom models)
  OWW_THRESHOLD     = 0.5                    # 0.3=sensitive, 0.7=strict

Install: pip install openwakeword
Built-in models download automatically on first run (~30MB).
Custom models come from kaggle_wake_job/train_leha_oww.ipynb (Google Colab).
"""

import collections
import queue
import math
import os
from pathlib import Path

import numpy as np
import sounddevice as sd

from . import config
from .audio import resolve_device
from scipy.signal import resample_poly


def _missing_external_data(model_path: str) -> list[str]:
    """Return missing files referenced by an ONNX external-data model.

    A tiny ``.onnx`` can be only a graph that points at a separate ``.data``
    weight file. Treating that graph as a complete wake model made the live
    listener crash-loop even though the path itself existed.
    """
    try:
        import onnx

        model = onnx.load(model_path, load_external_data=False)
        missing = []
        for tensor in model.graph.initializer:
            for entry in tensor.external_data:
                if entry.key != "location":
                    continue
                ref = Path(model_path).parent / entry.value
                if not ref.is_file() and str(ref) not in missing:
                    missing.append(str(ref))
        return missing
    except Exception:
        # The OpenWakeWord runtime remains the final model validator. Failure
        # to inspect metadata must not reject a normal self-contained model.
        return []


def _resolve_custom_models() -> list:
    """Build the list of custom model paths that actually exist on disk.

    Priority: OWW_CUSTOM_MODELS (list) > OWW_MODEL_PATH (single, legacy).
    Returns paths relative to BASE_DIR, or absolute if already absolute.
    Missing files are silently skipped (with a notice).
    """
    paths: list = []

    # New style: explicit list of custom model paths
    custom_list = list(getattr(config, "OWW_CUSTOM_MODELS", []) or [])
    for p in custom_list:
        p = (p or "").strip()
        if not p:
            continue
        full = p if os.path.isabs(p) else str(config.BASE_DIR / p)
        if os.path.isfile(full):
            missing = _missing_external_data(full)
            if missing:
                print(
                    f"[oww] incomplete model bundle, skipping {full}; "
                    f"missing: {', '.join(missing)}",
                    flush=True,
                )
            else:
                paths.append(full)
        else:
            print(f"[oww] custom model not found, skipping: {full}", flush=True)

    # Legacy: single OWW_MODEL_PATH (overrides OWW_MODEL_NAME when set)
    single = getattr(config, "OWW_MODEL_PATH", "").strip()
    if single:
        full = single if os.path.isabs(single) else str(config.BASE_DIR / single)
        if os.path.isfile(full) and full not in paths:
            missing = _missing_external_data(full)
            if missing:
                print(
                    f"[oww] incomplete OWW_MODEL_PATH, skipping {full}; "
                    f"missing: {', '.join(missing)}",
                    flush=True,
                )
            else:
                paths.append(full)
        elif not os.path.isfile(full):
            print(f"[oww] OWW_MODEL_PATH not found: {full}", flush=True)

    return paths


def is_available() -> bool:
    """True when openWakeWord is enabled AND at least one model can load."""
    if not getattr(config, "OWW_ENABLED", False):
        return False
    # Need either custom models present OR a built-in model name configured
    custom = _resolve_custom_models()
    fallback_name = getattr(config, "OWW_MODEL_NAME", "hey_jarvis")
    # If only a single legacy path was configured but missing, block start so
    # listen.py falls through to the next engine instead of crashing.
    single = getattr(config, "OWW_MODEL_PATH", "").strip()
    if single and not custom and not fallback_name:
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


def _update_hit_streaks(preds, names, threshold, counts, required_hits):
    """Return the strongest model after enough consecutive positive frames."""
    fired = None
    fired_score = 0.0
    for name in names:
        score = float(preds.get(name, 0.0))
        counts[name] = counts.get(name, 0) + 1 if score >= threshold else 0
        if counts[name] >= required_hits and score > fired_score:
            fired = name
            fired_score = score
    return fired, fired_score


class OWWListener:
    """openwakeword-based wake detector + VAD command capture in one mic stream.

    Loads one or more wake models. Any model scoring above threshold wakes Leha.

    Yields:
      None        — wake word detected
      np.ndarray  — 16kHz int16 command audio for Whisper STT
    """

    def __init__(self):
        from openwakeword.model import Model

        self._threshold = float(getattr(config, "OWW_THRESHOLD", 0.5))

        # Assemble the full model spec passed to openwakeword.Model().
        # Custom .onnx files take priority; fall back to a built-in name.
        custom_paths = _resolve_custom_models()
        # Derive the dict key openwakeword will use for each model's score.
        # Custom files key on the filename stem (e.g. "leha"); built-ins key
        # on their model name (e.g. "hey_jarvis").
        model_specs: list = []
        self._model_names: list = []

        for path in custom_paths:
            model_specs.append(path)
            stem = os.path.splitext(os.path.basename(path))[0]
            self._model_names.append(stem)

        if not model_specs:
            # No custom models — use the built-in fallback name.
            fallback_name = getattr(config, "OWW_MODEL_NAME", "hey_jarvis")
            model_specs.append(fallback_name)
            self._model_names.append(fallback_name)

        phrases = " / ".join(n.replace("_", " ") for n in self._model_names)
        print(f"[oww] loading {len(model_specs)} model(s): {phrases}...", flush=True)
        self._model = Model(wakeword_models=model_specs, inference_framework="onnx")
        print(f"[oww] ready — say '{phrases}' to wake Leha", flush=True)

    def stream_utterances(
        self,
        should_mute=None,
        barge_in_active=None,
        silence_ms: int = 900,
        max_seconds: float = 12.0,
        min_samples: int = 6000,
        start_rms: float = 180.0,
        session_active=None,
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
        hybrid_fallback = bool(
            getattr(config, "OWW_HYBRID_TRANSCRIPT_FALLBACK", True)
        )
        idle_start_rms = max(
            float(start_rms),
            float(getattr(config, "OWW_IDLE_VAD_START_RMS", start_rms)),
        )
        if hybrid_fallback:
            print(
                f"[oww] VAD gates: idle={idle_start_rms:.0f} "
                f"command={float(start_rms):.0f}",
                flush=True,
            )
        required_hits = max(1, int(getattr(config, "OWW_REQUIRED_HITS", 2)))
        hit_counts = {name: 0 for name in self._model_names}
        idle_pre: collections.deque = collections.deque(maxlen=3)
        idle_frames: list = []
        idle_started = False
        idle_silent_count = 0

        def prepare_audio(native_audio: np.ndarray) -> np.ndarray:
            out = _resample16k(native_audio, native)
            rv = float(np.sqrt(np.mean(out ** 2))) or 1.0
            if rv < 500:
                out = out * (1500.0 / rv)
            return np.clip(out, -32768, 32767).astype(np.int16)

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
                    idle_pre.clear()
                    idle_frames = []
                    idle_started = False
                    idle_silent_count = 0
                    # Keep woken state — barge-in detection after TTS done
                    continue

                if not woken:
                    # --- Wake detection via openwakeword (check ALL models) ---
                    chunk16k = _resample16k(raw, native)
                    # openwakeword expects int16 in float range or int16; pass as int16
                    chunk_int16 = np.clip(chunk16k, -32768, 32767).astype(np.int16)
                    preds = self._model.predict(chunk_int16)
                    # Near-miss telemetry: log real-voice scores so the
                    # threshold can be tuned from evidence, not guesses.
                    top_name = max(self._model_names, key=lambda n: preds.get(n, 0.0))
                    top_score = float(preds.get(top_name, 0.0))
                    if top_score >= 0.10:
                        import time as _t
                        now = _t.monotonic()
                        if now - getattr(self, "_last_score_log", 0.0) > 1.5:
                            self._last_score_log = now
                            print(
                                f"[oww] score {top_name}={top_score:.3f} "
                                f"(threshold={self._threshold})",
                                flush=True,
                            )
                    # Trigger if ANY loaded model exceeds threshold. Report
                    # which one fired so logs make tuning easier.
                    fired, fired_score = _update_hit_streaks(
                        preds,
                        self._model_names,
                        self._threshold,
                        hit_counts,
                        required_hits,
                    )
                    if fired is not None:
                        print(
                            f"[oww] WAKE WORD DETECTED "
                            f"('{fired.replace('_', ' ')}' score={fired_score:.3f})",
                            flush=True,
                        )
                        woken = True
                        wait_count = 0
                        pre.clear()
                        frames_buf = []
                        started = False
                        silent_count = 0
                        idle_pre.clear()
                        idle_frames = []
                        idle_started = False
                        idle_silent_count = 0
                        for name in hit_counts:
                            hit_counts[name] = 0
                        yield None
                    elif hybrid_fallback:
                        # Keep a normal utterance VAD running beside OWW. When
                        # the model misses, the completed audio is transcribed
                        # and must still pass AssistantSession's strict wake
                        # gate before any command can run.
                        rms = float(np.sqrt(np.mean(raw ** 2)))
                        if not idle_started:
                            idle_pre.append(raw)
                            if rms > idle_start_rms:
                                idle_frames.extend(idle_pre)
                                idle_pre.clear()
                                idle_started = True
                                idle_silent_count = 0
                        else:
                            idle_frames.append(raw)
                            if rms > idle_start_rms:
                                idle_silent_count = 0
                            else:
                                idle_silent_count += 1
                            if (
                                idle_silent_count >= silence_need
                                or len(idle_frames) >= max_blocks
                            ):
                                audio = np.concatenate(idle_frames)
                                idle_frames = []
                                idle_started = False
                                idle_silent_count = 0
                                idle_pre.clear()
                                out = prepare_audio(audio)
                                if len(out) >= min_samples:
                                    yield ("transcript_fallback", out)
                                while not q_in.empty():
                                    try:
                                        q_in.get_nowait()
                                    except Exception:
                                        break
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
                                # Resample + gentle normalize for STT.
                                out = prepare_audio(audio)
                                if len(out) >= min_samples:
                                    yield out
                                # After yielding: stay in command-capture mode if
                                # the session follow-up window is still open.
                                if session_active and session_active():
                                    wait_count = 0
                                    # Stay woken — ready for the next follow-up utterance
                                else:
                                    woken = False
