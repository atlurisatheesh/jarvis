"""Test WASAPI input devices (cleaner than MME). Talk the whole time.

Records a few seconds from each WASAPI mic, normalizes, transcribes.
Prints which device actually yields words.
"""
import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel

SR = 16000
SECS = 5
TARGET_RMS = 3000.0

hostapis = sd.query_hostapis()
wasapi_idx = next((i for i, h in enumerate(hostapis) if "WASAPI" in h["name"]), None)
print("Host APIs:", [h["name"] for h in hostapis], flush=True)
print("WASAPI index:", wasapi_idx, flush=True)

devs = [(i, d) for i, d in enumerate(sd.query_devices())
        if d["max_input_channels"] > 0 and d["hostapi"] == wasapi_idx]
print("WASAPI input devices:", [(i, d["name"][:35]) for i, d in devs], flush=True)

model = WhisperModel("tiny", device="cpu", compute_type="int8")


def norm(a):
    r = float(np.sqrt(np.mean(a ** 2))) or 1.0
    return np.clip(a * (TARGET_RMS / r), -32768, 32767)


for i, d in devs:
    print(f"\n--- device {i}: {d['name'][:40]} | speak now ({SECS}s) ---", flush=True)
    try:
        rec = sd.rec(int(SECS * SR), samplerate=SR, channels=1, dtype="int16", device=i)
        sd.wait()
        a = rec.flatten().astype(np.float32)
        rms, peak = float(np.sqrt(np.mean(a ** 2))), float(np.max(np.abs(a)))
        segs, _ = model.transcribe(norm(a) / 32768.0, beam_size=1, language="en")
        text = "".join(s.text for s in segs).strip()
        print(f"   rms={rms:.0f} peak={peak:.0f}  HEARD: '{text}'", flush=True)
    except Exception as e:
        print(f"   ERR {str(e)[:60]}", flush=True)
