"""Evaluate an ONNX Leha wake model against held-out private WAV recordings."""
from __future__ import annotations

import argparse
import json
import math
import sys
import wave
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jarvis_ai import config


RATE = 16_000
WINDOW = RATE


def _read(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as source:
        if source.getnchannels() != 1 or source.getsampwidth() != 2:
            raise ValueError("expected mono 16-bit WAV")
        rate = source.getframerate()
        audio = np.frombuffer(source.readframes(source.getnframes()), dtype=np.int16).astype(np.float32)
    if rate != RATE:
        divisor = math.gcd(rate, RATE)
        audio = resample_poly(audio, RATE // divisor, rate // divisor)
    return audio / 32768.0


def _windows(audio: np.ndarray):
    if len(audio) <= WINDOW:
        out = np.zeros(WINDOW, dtype=np.float32)
        out[:len(audio)] = audio
        yield out
        return
    hop = WINDOW // 4
    for offset in range(0, len(audio) - WINDOW + 1, hop):
        yield audio[offset:offset + WINDOW]


def _score(session, input_name: str, path: Path) -> float:
    scores = []
    for part in _windows(_read(path)):
        logit = float(np.asarray(session.run(None, {input_name: part[None, None, :].astype(np.float32)})[0]).reshape(-1)[0])
        scores.append(1.0 / (1.0 + math.exp(-logit)))
    return max(scores, default=0.0)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=config.CUSTOM_WAKE_MODEL_PATH)
    parser.add_argument("--positive", required=True, help="held-out Leha clips directory")
    parser.add_argument("--negative", required=True, help="held-out non-Leha clips directory")
    parser.add_argument("--threshold", type=float, default=config.CUSTOM_WAKE_THRESHOLD)
    parser.add_argument("--report", default="processed/leha_wake_evaluation.json")
    args = parser.parse_args()

    import onnxruntime as ort

    model = Path(args.model)
    positives = sorted(Path(args.positive).glob("*.wav"))
    negatives = sorted(Path(args.negative).glob("*.wav"))
    if len(positives) < 10 or len(negatives) < 30:
        raise SystemExit("Need at least 10 held-out positives and 30 held-out negatives.")

    session = ort.InferenceSession(str(model), providers=["CPUExecutionProvider"])
    input_name = session.get_inputs()[0].name
    positive_scores = [_score(session, input_name, path) for path in positives]
    negative_scores = [_score(session, input_name, path) for path in negatives]
    positives_hit = sum(score >= args.threshold for score in positive_scores)
    negatives_hit = sum(score >= args.threshold for score in negative_scores)
    report = {
        "model": str(model),
        "threshold": args.threshold,
        "positive_clips": len(positives),
        "negative_clips": len(negatives),
        "wake_recall": round(positives_hit / len(positives), 4),
        "false_wake_rate": round(negatives_hit / len(negatives), 4),
        "positive_score_range": [round(min(positive_scores), 4), round(max(positive_scores), 4)],
        "negative_score_range": [round(min(negative_scores), 4), round(max(negative_scores), 4)],
    }
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    if report["wake_recall"] < 0.95 or report["false_wake_rate"] > 0.01:
        raise SystemExit("MODEL NOT APPROVED: keep CUSTOM_WAKE_ENABLED = False.")
    print("MODEL APPROVED: enable only after a live-room false-wake test.")


if __name__ == "__main__":
    main()
