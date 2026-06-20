"""Capture the Senary virtual mic (dev 27) at native rate, resample, transcribe.
This device carried real audio in the scans. Speak the full window.
"""
import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel

DEV = 27
SECS = 8
TARGET_RMS = 3000.0
info = sd.query_devices(DEV)
native = int(info["default_samplerate"])
print(f"device {DEV}: {info['name'][:40]} native_sr={native}", flush=True)

print(f"RECORDING {SECS}s at {native}Hz — speak NOW...", flush=True)
rec = sd.rec(int(SECS * native), samplerate=native, channels=1, dtype="int16", device=DEV)
sd.wait()
a = rec.flatten().astype(np.float32)
print(f"raw_rms={np.sqrt(np.mean(a**2)):.0f} peak={np.max(np.abs(a)):.0f}", flush=True)

n16 = int(len(a) * 16000 / native)
a16 = np.interp(np.linspace(0, len(a), n16, endpoint=False), np.arange(len(a)), a)
r = float(np.sqrt(np.mean(a16 ** 2))) or 1.0
a16 = np.clip(a16 * (TARGET_RMS / r), -32768, 32767)

model = WhisperModel("tiny", device="cpu", compute_type="int8")
segs, _ = model.transcribe(a16 / 32768.0, beam_size=1, language="en")
text = "".join(s.text for s in segs).strip()
print(f"\nHEARD: '{text}'", flush=True)
print("VERDICT: " + ("SENARY MIC WORKS!" if len(text) > 4 else "nothing usable"), flush=True)
