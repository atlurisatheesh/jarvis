"""Test the Jabra headset mic (WASAPI default) + transcribe."""
import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel

# resolve headset by name (index can shift)
dev = None
for i, d in enumerate(sd.query_devices()):
    if d["max_input_channels"] > 0 and "Jabra" in d["name"]:
        dev = i
        break
if dev is None:
    dev = sd.default.device[0]
info = sd.query_devices(dev)
native = int(info["default_samplerate"])
print(f"device {dev}: {info['name'][:40]} native={native}", flush=True)

SECS = 6
print(f"RECORDING {SECS}s — speak NOW...", flush=True)
rec = sd.rec(int(SECS * native), samplerate=native, channels=1, dtype="int16", device=dev)
sd.wait()
a = rec.flatten().astype(np.float32)
print(f"raw_rms={np.sqrt(np.mean(a**2)):.0f} peak={np.max(np.abs(a)):.0f}", flush=True)
if native != 16000:
    n = int(len(a) * 16000 / native)
    a = np.interp(np.linspace(0, len(a), n, endpoint=False), np.arange(len(a)), a)
model = WhisperModel("tiny", device="cpu", compute_type="int8")
segs, _ = model.transcribe(a / 32768.0, beam_size=1, language="en")
text = "".join(s.text for s in segs).strip()
print(f"\nHEARD: '{text}'", flush=True)
print(f"DEVICE_INDEX={dev} NATIVE_SR={native}", flush=True)
print("VERDICT: " + ("HEADSET WORKS!" if len(text) > 4 else "nothing"), flush=True)
