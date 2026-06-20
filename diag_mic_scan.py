"""Scan every input device for actual captured level. Talk during the whole run."""
import numpy as np
import sounddevice as sd

DUR = 1.8
SR = 16000
print("Scanning input devices. KEEP TALKING the whole time...", flush=True)
results = []
for i, d in enumerate(sd.query_devices()):
    if d["max_input_channels"] < 1:
        continue
    name = d["name"][:38]
    try:
        rec = sd.rec(int(DUR * SR), samplerate=SR, channels=1,
                     dtype="int16", device=i)
        sd.wait()
        rms = float(np.sqrt(np.mean(rec.astype(np.float32) ** 2)))
        results.append((rms, i, name))
        print(f"  dev {i:2d}  rms={rms:7.0f}  {name}", flush=True)
    except Exception as e:
        print(f"  dev {i:2d}  ERR {str(e)[:40]}  {name}", flush=True)

results.sort(reverse=True)
print("\nTOP (loudest = working mic):", flush=True)
for rms, i, name in results[:4]:
    print(f"  >> device {i}  rms={rms:.0f}  {name}", flush=True)
