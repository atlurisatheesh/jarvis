"""Probe wake on device 1 (Jabra MME) at 16k — mirrors the server path.
Prints mic level heartbeat + any wake score. Say 'Hey Jarvis' repeatedly.
"""
import queue
import time

import numpy as np
import sounddevice as sd
from openwakeword.model import Model

SR = 16000
CHUNK = 1280
SECONDS = 25
DEVICE = 1
GAIN = 2.0

print(f"device={DEVICE} gain={GAIN} sr={SR}", flush=True)
m = Model(wakeword_models=["hey_jarvis_v0.1"], inference_framework="onnx")
q = queue.Queue()


def cb(indata, frames, t, s):
    if s:
        print(f"status {s}", flush=True)
    f = indata.copy()
    f = np.clip(f.astype(np.float32) * GAIN, -32768, 32767).astype(np.int16)
    q.put(f)


print(f"LISTENING {SECONDS}s — say 'Hey Jarvis' NOW...", flush=True)
max_score = max_rms = 0.0
last_beat = time.time()
with sd.InputStream(samplerate=SR, channels=1, blocksize=CHUNK,
                    dtype="int16", device=DEVICE, callback=cb):
    start = time.time()
    while time.time() - start < SECONDS:
        f = q.get().flatten()
        rms = float(np.sqrt(np.mean(f.astype(np.float32) ** 2)))
        sc = float(m.predict(f).get("hey_jarvis_v0.1", 0.0))
        max_score, max_rms = max(max_score, sc), max(max_rms, rms)
        if sc > 0.05:
            print(f"  wake_score={sc:.3f} rms={rms:.0f}", flush=True)
        if time.time() - last_beat > 2:
            print(f"  ...level rms={rms:.0f}", flush=True)
            last_beat = time.time()

print(f"DONE max_rms={max_rms:.0f} max_wake_score={max_score:.3f}", flush=True)
