"""Record clean local wake-word clips for a future openWakeWord Leha model.

Run from D:\\jarvis:
    python tools/record_leha_wake_samples.py

This recorder does not upload audio or train a model. It creates the small,
labelled wake-word dataset needed before local/GPU training is useful.
"""

from __future__ import annotations

import argparse
import sys
import time
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd
from scipy.signal import resample_poly

# Scripts launched from tools/ do not automatically see the repository package.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from jarvis_ai import config
from jarvis_ai.audio import _capture_rates, resolve_device, stream_utterances


SAMPLE_RATE = 16_000
PHRASES = ("Leha", "Hey Leha", "Leha listen")


def write_wav(path: Path, audio: np.ndarray) -> None:
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(SAMPLE_RATE)
        out.writeframes(audio.astype(np.int16).tobytes())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=30, help="number of clips")
    parser.add_argument("--seconds", type=float, default=2.0, help="clip duration")
    parser.add_argument(
        "--auto",
        action="store_true",
        help="record on a timed countdown instead of waiting for Enter each clip",
    )
    parser.add_argument("--gap", type=float, default=1.5, help="pause between automatic clips")
    parser.add_argument(
        "--continuous",
        action="store_true",
        help="save each spoken phrase until --count clips are collected",
    )
    parser.add_argument(
        "--output", default="jarvis_ai/voices/wake_leha", help="output directory"
    )
    args = parser.parse_args()
    if args.count < 1 or args.seconds <= 0:
        raise SystemExit("--count and --seconds must be positive")

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    device = resolve_device(config.MIC_DEVICE)
    native_rate = None
    for candidate in _capture_rates(device):
        try:
            sd.check_input_settings(
                device=device, samplerate=candidate, channels=1, dtype="int16"
            )
            native_rate = candidate
            break
        except Exception:
            continue
    if native_rate is None:
        raise SystemExit(f"Could not open microphone {device!r} at a supported rate.")

    print(
        f"Recording {args.count} clips from microphone {device!r} at {native_rate} Hz into {output}."
    )
    print("Use a quiet room. Speak naturally after each countdown; vary distance and tone.")
    if args.continuous:
        print("Continuous mode starts in 5 seconds. Say 'Leha', wait one second, and repeat.")
        time.sleep(5)
        saved = 0
        for clip in stream_utterances(
            silence_ms=650, start_rms=150, max_seconds=4, min_samples=4_000
        ):
            rms = float(np.sqrt(np.mean(clip.astype(np.float32) ** 2)))
            path = output / f"leha_{saved + 1:03d}.wav"
            write_wav(path, clip)
            saved += 1
            print(f"Saved {path.name} (RMS {rms:.0f})", flush=True)
            if saved >= args.count:
                break
        print("Done. Keep the clips private. Next step: train/export leha.onnx, then set")
        print("OWW_MODEL_PATH to that file and OWW_ENABLED = True in jarvis_ai/config.py.")
        return
    if args.auto:
        print("Automatic recording starts in 8 seconds. Speak each prompt when shown.")
        time.sleep(8)

    frames = int(native_rate * args.seconds)
    for index in range(args.count):
        phrase = PHRASES[index % len(PHRASES)]
        if not args.auto:
            input(f"[{index + 1:02d}/{args.count:02d}] Press Enter, then say: {phrase!r} ")
        else:
            print(f"[{index + 1:02d}/{args.count:02d}] Next phrase: {phrase!r}")
        for number in (3, 2, 1):
            print(number, flush=True)
            time.sleep(0.6)
        print("Speak now", flush=True)
        audio = sd.rec(
            frames,
            samplerate=native_rate,
            channels=1,
            dtype="int16",
            device=device,
        )
        sd.wait()
        clip = audio.reshape(-1)
        if native_rate != SAMPLE_RATE:
            from math import gcd
            divisor = gcd(native_rate, SAMPLE_RATE)
            clip = resample_poly(
                clip.astype(np.float32), SAMPLE_RATE // divisor, native_rate // divisor
            ).astype(np.int16)
        rms = float(np.sqrt(np.mean(clip.astype(np.float32) ** 2)))
        path = output / f"leha_{index + 1:03d}.wav"
        write_wav(path, clip)
        print(f"Saved {path.name} (RMS {rms:.0f})")
        if args.auto and index + 1 < args.count:
            time.sleep(args.gap)

    print("Done. Keep the clips private. Next step: train/export leha.onnx, then set")
    print("OWW_MODEL_PATH to that file and OWW_ENABLED = True in jarvis_ai/config.py.")


if __name__ == "__main__":
    main()
