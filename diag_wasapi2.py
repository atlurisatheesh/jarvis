"""Record WASAPI Intel mic at native rate, resample to 16k, transcribe."""
import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel

DEV = 9
SECS = 8
TARGET_RMS = 3000.0
info = sd.query_devices(DEV)
native = int(info["default_samplerate"])
print(f"device {DEV}: {info['name'][:40]}  native_sr={native}", flush=True)

print(f"RECORDING {SECS}s at {native}Hz — speak NOW...", flush=True)
rec = sd.rec(int(SECS * native), samplerate=native, channels=1, dtype="int16", device=DEV)
sd.wait()
a = rec.flatten().astype(np.float32)
rms, peak = float(np.sqrt(np.mean(a ** 2))), float(np.max(np.abs(a)))
print(f"raw_rms={rms:.0f} peak={peak:.0f}", flush=True)

# resample native -> 16000 via linear interpolation
n16 = int(len(a) * 16000 / native)
x = np.linspace(0, len(a), n16, endpoint=False)
a16 = np.interp(x, np.arange(len(a)), a)
# RMS normalize
r = float(np.sqrt(np.mean(a16 ** 2))) or 1.0
a16 = np.clip(a16 * (TARGET_RMS / r), -32768, 32767)

print("Transcribing...", flush=True)
model = WhisperModel("tiny", device="cpu", compute_type="int8")
segs, _ = model.transcribe(a16 / 32768.0, beam_size=1, language="en")
text = "".join(s.text for s in segs).strip()
print(f"\nHEARD: '{text}'", flush=True)
print("VERDICT: " + ("WASAPI MIC WORKS!" if text else "still nothing"), flush=True)
