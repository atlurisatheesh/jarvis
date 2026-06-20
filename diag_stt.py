"""Record, RMS-normalize, transcribe. Robust to quiet OR loud mics.

Speak 'hello jarvis can you hear me' for the full 10 seconds.
"""
import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel

SR = 16000
SECS = 10
TARGET_RMS = 3000.0
CANDIDATES = [27, 12, 5]  # live mic from scans (default device is dead)


def normalize(audio: np.ndarray) -> np.ndarray:
    rms = float(np.sqrt(np.mean(audio ** 2))) or 1.0
    scaled = audio * (TARGET_RMS / rms)
    return np.clip(scaled, -32768, 32767)


dev = None
for c in CANDIDATES:
    try:
        sd.check_input_settings(device=c, samplerate=SR, channels=1, dtype="int16")
        dev = c
        break
    except Exception:
        continue

print(f"Using device {dev}. RECORDING {SECS}s — keep speaking NOW...", flush=True)
rec = sd.rec(int(SECS * SR), samplerate=SR, channels=1, dtype="int16", device=dev)
sd.wait()
audio = rec.flatten().astype(np.float32)
rms = float(np.sqrt(np.mean(audio ** 2)))
peak = float(np.max(np.abs(audio)))
norm = normalize(audio)
print(f"raw_rms={rms:.0f}  peak={peak:.0f}  -> normalized to rms {TARGET_RMS:.0f}", flush=True)

print("Transcribing...", flush=True)
model = WhisperModel("tiny", device="cpu", compute_type="int8")
segs, _ = model.transcribe(norm / 32768.0, beam_size=1, language="en")
text = "".join(s.text for s in segs).strip()
print(f"\nHEARD: '{text}'", flush=True)
print("VERDICT: " + ("MIC USABLE!" if text else "still nothing — try a different device index"),
      flush=True)
