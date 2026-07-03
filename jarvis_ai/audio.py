"""Robust mic capture: native-rate record + VAD + resample to 16k.

This is the path proven to work on this machine (the live 16k openwakeword
stream did not). Used by push-to-talk and any STT capture.

Fixes applied (see HANDOFF.md):
 - Anti-aliased resample via scipy.signal.resample_poly (was np.interp).
 - Gentle normalization only when audio is very quiet (was target_rms=3000).
 - Pre-buffer keeps 3 chunks before VAD fires so word onsets aren't clipped.
 - Diagnostic: saves cap.wav for inspection (_SAVE_CAPTURE flag).
"""
import collections
import queue

import numpy as np
import sounddevice as sd
from scipy.signal import resample_poly

from . import config

# Set True to write every captured utterance to cap.wav for debugging.
_SAVE_CAPTURE = False


def _input_devices():
    """Return ``(index, device)`` pairs for devices that can capture audio."""
    try:
        return [
            (i, d) for i, d in enumerate(sd.query_devices())
            if int(d.get("max_input_channels", 0)) > 0
        ]
    except Exception:
        return []


def _default_input_device():
    """Best-effort OS default input index, or None if unavailable."""
    try:
        default = sd.default.device
        idx = default[0] if isinstance(default, (list, tuple)) else default
        if idx is not None and idx >= 0:
            dev = sd.query_devices(int(idx))
            if int(dev.get("max_input_channels", 0)) > 0:
                return int(idx)
    except Exception:
        pass
    return None


def resolve_device(spec):
    """Resolve configured mic to a valid input index.

    ``sounddevice`` indices can change when a headset/Bluetooth device is
    unplugged or Windows changes defaults. A stale integer index used to crash
    with ``Invalid device``. We now keep the configured device when valid and
    otherwise fall back to the OS default input, then the first input device.
    """
    inputs = _input_devices()
    if spec is None:
        default = _default_input_device()
        return default if default is not None else (inputs[0][0] if inputs else None)
    if isinstance(spec, int):
        for i, _d in inputs:
            if i == spec:
                return spec
        fallback = _default_input_device()
        chosen = fallback if fallback is not None else (inputs[0][0] if inputs else None)
        if chosen is not None:
            print(f"[audio] configured mic device {spec} is unavailable; using input device {chosen}", flush=True)
        return chosen
    hostapis = sd.query_hostapis()
    mme = next((i for i, h in enumerate(hostapis) if h["name"] == "MME"), None)
    matches = [(i, d) for i, d in inputs
               if spec.lower() in d["name"].lower()]
    if not matches:
        fallback = _default_input_device()
        return fallback if fallback is not None else (inputs[0][0] if inputs else None)
    for i, d in matches:
        if d["hostapi"] == mme:
            return i
    return matches[0][0]


def _capture_rates(dev):
    """Try 16 kHz first, then the driver-advertised rate for unstable devices."""
    rates = [config.SAMPLE_RATE]
    if dev is not None:
        try:
            rates.append(int(sd.query_devices(dev)["default_samplerate"]))
        except Exception:
            pass
    return list(dict.fromkeys(rates))


def record_command(max_seconds=10, silence_ms=900, start_rms=200) -> np.ndarray:
    """Record from the configured mic until silence; return 16 kHz int16 mono."""
    dev = resolve_device(config.MIC_DEVICE)
    # This microphone rejects a 16 kHz input stream but accepts its native
    # 48 kHz rate. Capture natively, then resample below for STT.
    native = _capture_rates(dev)[-1]
    block = max(160, int(native * 0.05))  # ~50 ms
    chunk_ms = block / native * 1000.0
    silence_need = max(1, int(silence_ms / chunk_ms))
    max_blocks = int(max_seconds * 1000 / chunk_ms)

    q: queue.Queue = queue.Queue()

    def cb(indata, frames, t, s):
        q.put(indata.copy())

    # Keep a rolling pre-buffer so we don't clip the start of speech.
    pre_buf: collections.deque = collections.deque(maxlen=3)
    frames, started, silent = [], False, 0

    with sd.InputStream(samplerate=native, channels=1, blocksize=block,
                        dtype="int16", device=dev, callback=cb):
        for _ in range(max_blocks):
            f = q.get().flatten().astype(np.float32)
            rms = float(np.sqrt(np.mean(f ** 2)))

            if not started:
                pre_buf.append(f)
                if rms > start_rms:
                    # Speech detected — flush the pre-buffer so we keep the
                    # onset of the word that triggered detection.
                    frames.extend(pre_buf)
                    pre_buf.clear()
                    started, silent = True, 0
            else:
                frames.append(f)
                if rms > start_rms:
                    silent = 0
                else:
                    silent += 1
                    if silent >= silence_need:
                        break

    if not frames or not started:
        return np.zeros(0, dtype=np.int16)  # no speech detected

    audio = np.concatenate(frames)

    # --- Resample with proper anti-aliasing ---
    if native != 16000:
        from math import gcd
        g = gcd(native, 16000)
        audio = resample_poly(audio, 16000 // g, native // g).astype(np.float32)

    # --- Gentle normalization: only boost very quiet audio ---
    rms_val = float(np.sqrt(np.mean(audio ** 2))) or 1.0
    if rms_val < 500:
        audio = audio * (1500.0 / rms_val)
    audio = np.clip(audio, -32768, 32767)
    result = audio.astype(np.int16)

    # --- Diagnostic: save capture for inspection ---
    if _SAVE_CAPTURE:
        try:
            import soundfile as sf
            sf.write("cap.wav", result, 16000)
            print("[audio] saved cap.wav for inspection", flush=True)
        except Exception as e:
            print(f"[audio] could not save cap.wav: {e}", flush=True)

    return result


def _to16k_int16(audio: np.ndarray, native: int) -> np.ndarray:
    if native != 16000:
        from math import gcd
        g = gcd(native, 16000)
        audio = resample_poly(audio, 16000 // g, native // g).astype(np.float32)
    rms = float(np.sqrt(np.mean(audio ** 2))) or 1.0
    if rms < 500:
        audio = audio * (1500.0 / rms)
    return np.clip(audio, -32768, 32767).astype(np.int16)


def stream_utterances(should_mute=None, barge_in_active=None, silence_ms=900,
                      start_rms=180, max_seconds=15, min_samples=6000):
    """Alexa-style: ONE mic stream that never closes. Yields each spoken
    utterance (16 kHz int16) as it completes, segmented by silence (VAD).

    should_mute(): callable -> True while JARVIS is speaking; frames are
    dropped then so it never transcribes its own voice.

    barge_in_active(): callable -> True when we want to listen for
    interruptions during TTS. Raises the VAD threshold instead of muting.
    """
    dev = resolve_device(config.MIC_DEVICE)
    last_error = None
    for native in _capture_rates(dev):
        block = max(160, int(native * 0.05))
        chunk_ms = block / native * 1000.0
        silence_need = max(1, int(silence_ms / chunk_ms))
        max_blocks = int(max_seconds * 1000 / chunk_ms)
        q: queue.Queue = queue.Queue()
        def cb(indata, frames, t, s): q.put(indata.copy())
        pre = collections.deque(maxlen=3)
        frames, started, silent = [], False, 0
        try:
            stream = sd.InputStream(samplerate=native, channels=1, blocksize=block,
                                    dtype="int16", device=dev, callback=cb)
            stream.start()
        except Exception as exc:
            last_error = exc
            continue
        print(f"[audio] capture rate {native} Hz", flush=True)
        try:
          while True:
            f = q.get().flatten().astype(np.float32)

            # barge-in mode: keep stream alive but require louder audio
            effective_start_rms = start_rms
            if barge_in_active and barge_in_active():
                effective_start_rms = int(start_rms * config.BARGE_IN_RMS_BOOST)
                # drain stale queue so we don't process minutes of backlog
                while not q.empty():
                    try:
                        q.get_nowait()
                    except Exception:
                        break

            # drop everything while JARVIS is talking (echo suppression)
            if should_mute and should_mute():
                # drain the queue so stale frames don't leak through on un-mute
                while not q.empty():
                    try:
                        q.get_nowait()
                    except Exception:
                        break
                pre.clear(); frames = []; started = False; silent = 0
                continue

            rms = float(np.sqrt(np.mean(f ** 2)))
            if not started:
                pre.append(f)
                if rms > effective_start_rms:
                    frames.extend(pre); pre.clear()
                    started, silent = True, 0
            else:
                frames.append(f)
                if rms > effective_start_rms:
                    silent = 0
                else:
                    silent += 1
                    if silent >= silence_need or len(frames) >= max_blocks:
                        audio = np.concatenate(frames)
                        frames, started, silent = [], False, 0
                        out = _to16k_int16(audio, native)
                        if len(out) >= min_samples:
                            yield out
        finally:
            stream.stop(); stream.close()
    raise RuntimeError(f"Could not open microphone: {last_error}")


def calibrate_noise_floor(dev=None, seconds=1.5):
    """Measure background RMS on the mic to set a dynamic VAD threshold."""
    if dev is None:
        dev = resolve_device(config.MIC_DEVICE)
    last_error = None
    for native in _capture_rates(dev):
        block = max(160, int(native * 0.05))
        q: queue.Queue = queue.Queue()
        def cb(indata, frames, t, s): q.put(indata.copy())
        try:
            with sd.InputStream(samplerate=native, channels=1, blocksize=block,
                                dtype="int16", device=dev, callback=cb):
                samples = [q.get().flatten().astype(np.float32)
                           for _ in range(int(seconds * native / block))]
            audio = np.concatenate(samples)
            return max(50.0, float(np.sqrt(np.mean(audio ** 2))))
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"Could not calibrate microphone: {last_error}")
