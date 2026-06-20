"""Diagnose openwakeword scores live. Run: python diag_oww.py"""
import math
import time
import numpy as np
import sounddevice as sd
from scipy.signal import resample_poly
from openwakeword.model import Model
from jarvis_ai.audio import resolve_device
from jarvis_ai import config

dev = resolve_device(config.MIC_DEVICE)
info = sd.query_devices(dev) if dev is not None else sd.query_devices(kind="input")
native = int(info["default_samplerate"])
print(f"Mic device: {info['name']}  native={native}Hz")

model = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
block = max(160, int(native * 1280 / 16000))
print(f"Block={block} samples (~{block/native*1000:.0f}ms)")
print("Say 'hey jarvis' — showing rms + score for 15 seconds:")
print("-" * 50)

max_score = 0.0
with sd.InputStream(samplerate=native, channels=1, blocksize=block, dtype="int16", device=dev) as s:
    start = time.time()
    while time.time() - start < 15:
        raw, _ = s.read(block)
        f = raw.flatten().astype(np.float32)
        rms = float(np.sqrt(np.mean(f ** 2)))
        g = math.gcd(native, 16000)
        r = resample_poly(f, 16000 // g, native // g).astype(np.int16)
        preds = model.predict(r)
        score = float(preds.get("hey_jarvis", 0.0))
        max_score = max(max_score, score)
        if rms > 100 or score > 0.05:
            bar = "#" * int(score * 40)
            print(f"rms={rms:6.0f}  score={score:.3f}  {bar}")

print("-" * 50)
print(f"Max score seen: {max_score:.3f}  (threshold=0.5)")
if max_score < 0.1:
    print("PROBLEM: mic not picking up audio OR 'hey jarvis' not matching.")
elif max_score < 0.5:
    print(f"CLOSE: max score {max_score:.3f} below threshold 0.5. Try OWW_THRESHOLD={max_score*0.8:.2f}")
else:
    print("OK: should fire in normal use.")
