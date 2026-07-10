"""Remove background noise from Leha's owner-voice audio.

Cleans two things:
1. voices/clone_cache/*.wav — the pre-rendered owner-voice phrases (in place,
   originals backed up to clone_cache/raw/ once).
2. voices/leha_reference_mix.wav — the clone reference built from WhatsApp
   audio, written to leha_reference_clean.wav. Re-rendering phrases from the
   clean reference (tools/prerender_clone_phrases.py after pointing
   CLONE_TTS_REFERENCE at it) gives the best quality.

Pipeline per file: spectral noise reduction (noisereduce) -> gentle high-pass
(remove rumble) -> peak normalize -> trim leading/trailing silence.

Usage (from D:\\jarvis):
    python tools/denoise_clone_cache.py            # clean cache + reference
    python tools/denoise_clone_cache.py --cache    # only the 13 phrase wavs
    python tools/denoise_clone_cache.py --reference  # only the reference mix
"""
import argparse
import shutil
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jarvis_ai import config  # noqa: E402


def _high_pass(audio: np.ndarray, sr: int, cutoff: float = 80.0) -> np.ndarray:
    from scipy.signal import butter, sosfilt
    sos = butter(4, cutoff, btype="highpass", fs=sr, output="sos")
    return sosfilt(sos, audio)


def _trim_silence(audio: np.ndarray, sr: int, threshold: float = 0.01,
                  pad_ms: int = 120) -> np.ndarray:
    envelope = np.abs(audio)
    above = np.where(envelope > threshold * np.max(envelope))[0]
    if len(above) == 0:
        return audio
    pad = int(sr * pad_ms / 1000)
    start = max(0, above[0] - pad)
    end = min(len(audio), above[-1] + pad)
    return audio[start:end]


def clean_file(src: Path, dst: Path) -> bool:
    import noisereduce as nr
    try:
        audio, sr = sf.read(str(src), dtype="float32")
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        cleaned = nr.reduce_noise(y=audio, sr=sr, stationary=True, prop_decrease=0.9)
        cleaned = _high_pass(cleaned, sr)
        peak = np.max(np.abs(cleaned))
        if peak > 0:
            cleaned = cleaned * (0.95 / peak)
        cleaned = _trim_silence(cleaned, sr)
        sf.write(str(dst), cleaned.astype(np.float32), sr)
        return True
    except Exception as e:
        print(f"[denoise]   FAILED {src.name}: {e}")
        return False


def clean_cache() -> int:
    cache = Path(config.CLONE_PHRASE_CACHE_DIR)
    raw = cache / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    wavs = sorted(cache.glob("*.wav"))
    if not wavs:
        print("[denoise] no cached phrases found")
        return 0
    done = 0
    for wav in wavs:
        backup = raw / wav.name
        if not backup.exists():
            shutil.copy2(wav, backup)
        # Always clean from the raw original so re-runs don't double-process.
        if clean_file(backup, wav):
            done += 1
            print(f"[denoise] cleaned {wav.name}")
    print(f"[denoise] cache: {done}/{len(wavs)} cleaned (originals in {raw})")
    return done


def clean_reference() -> bool:
    src = Path(config.CLONE_TTS_REFERENCE)
    if not src.exists():
        print(f"[denoise] reference not found: {src}")
        return False
    dst = src.with_name("leha_reference_clean.wav")
    if clean_file(src, dst):
        print(f"[denoise] clean reference written: {dst}")
        print("[denoise] to re-render phrases from it:")
        print("  python tools/prerender_clone_phrases.py  (after clearing clone_cache/*.wav)")
        return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", action="store_true", help="only clean cached phrases")
    parser.add_argument("--reference", action="store_true", help="only clean the reference mix")
    args = parser.parse_args()
    do_cache = args.cache or not args.reference
    do_ref = args.reference or not args.cache
    ok = True
    if do_cache:
        ok = clean_cache() > 0 and ok
    if do_ref:
        ok = clean_reference() and ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
