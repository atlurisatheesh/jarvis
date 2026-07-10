"""Wake-word model evaluator.

Slides a 1-second window across held-out WAV recordings, runs ONNX inference,
and reports wake recall and false-wake rates.

Approval gate: ≥ 95 % recall AND ≤ 1 % false-wake, or exits with
"MODEL NOT APPROVED".

Usage:
    python -m jarvis_ai.wake_evaluator --model leha.onnx --positive ./held_out/positive --negative ./held_out/negative
    python -m jarvis_ai.wake_evaluator --model leha.onnx --positive ./held_out/positive --negative ./held_out/negative --threshold 0.7
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np


def _load_wav_16k(path: str | Path) -> tuple[np.ndarray, int]:
    """Load WAV, return (float32 samples, original sample rate)."""
    import soundfile as sf
    data, sr = sf.read(str(path), dtype="float32")
    if data.ndim > 1:
        data = data[:, 0]
    return data, sr


def _resample(data: np.ndarray, from_sr: int, to_sr: int = 16000) -> np.ndarray:
    if from_sr == to_sr:
        return data
    from scipy.signal import resample_poly
    return resample_poly(data, to_sr, from_sr)


def _evaluate_model(
    model_path: str | Path,
    positive_dir: str | Path,
    negative_dir: str | Path,
    threshold: float = 0.5,
    hop_sec: float = 0.25,
    window_sec: float = 1.0,
    required_hits: int = 1,
) -> dict:
    """Run evaluation and return metrics dict."""
    import onnxruntime as ort

    session = ort.InferenceSession(str(model_path))
    input_name = session.get_inputs()[0].name
    input_shape = session.get_inputs()[0].shape
    is_openwakeword = len(input_shape) == 3 and input_shape[-2:] == [16, 96]
    oww_model = None
    oww_key = Path(model_path).stem
    if is_openwakeword:
        from openwakeword.model import Model

        oww_model = Model(
            wakeword_models=[str(model_path)],
            inference_framework="onnx",
        )
    window_len = int(window_sec * 16000)
    hop_len = int(hop_sec * 16000)

    def _score_clip(path: str | Path) -> float:
        """Slide window across clip, return max score."""
        data, sr = _load_wav_16k(path)
        data = _resample(data, sr)
        if is_openwakeword:
            assert oww_model is not None
            oww_model.reset()
            pcm = np.clip(data, -1.0, 1.0)
            pcm = (pcm * 32767.0).astype(np.int16)
            # A little surrounding silence mirrors a continuous microphone
            # stream and lets the feature buffer settle around short clips.
            pad = np.zeros(3200, dtype=np.int16)
            pcm = np.concatenate((pad, pcm, pad))
            frame_len = 1280
            remainder = len(pcm) % frame_len
            if remainder:
                pcm = np.pad(pcm, (0, frame_len - remainder))
            max_score = 0.0
            hit_streak = 0
            max_hit_streak = 0
            for start in range(0, len(pcm), frame_len):
                scores = oww_model.predict(pcm[start : start + frame_len])
                score = float(scores.get(oww_key, 0.0))
                max_score = max(max_score, score)
                hit_streak = hit_streak + 1 if score >= threshold else 0
                max_hit_streak = max(max_hit_streak, hit_streak)
            return max_score if max_hit_streak >= max(1, required_hits) else 0.0
        if len(data) < window_len:
            return 0.0
        max_score = 0.0
        for start in range(0, len(data) - window_len + 1, hop_len):
            window = data[start : start + window_len].astype(np.float32)
            if len(input_shape) == 3:
                window = window.reshape(1, 1, -1)
            else:
                window = window.reshape(1, -1)
            logit = session.run(None, {input_name: window})[0][0]
            score = float(1.0 / (1.0 + np.exp(-logit)))  # sigmoid
            max_score = max(max_score, score)
        return max_score

    # Evaluate positives
    pos_files = sorted(Path(positive_dir).rglob("*.wav"))
    pos_scores = []
    for f in pos_files:
        score = _score_clip(f)
        pos_scores.append({"file": f.name, "score": round(score, 4)})

    # Evaluate negatives
    neg_files = sorted(Path(negative_dir).rglob("*.wav"))
    neg_scores = []
    for f in neg_files:
        score = _score_clip(f)
        neg_scores.append({"file": f.name, "score": round(score, 4)})

    recall = (
        sum(1 for s in pos_scores if s["score"] >= threshold) / len(pos_scores)
        if pos_scores
        else 0.0
    )
    false_wake = (
        sum(1 for s in neg_scores if s["score"] >= threshold) / len(neg_scores)
        if neg_scores
        else 0.0
    )

    results = {
        "model": str(model_path),
        "threshold": threshold,
        "window_sec": window_sec,
        "hop_sec": hop_sec,
        "required_hits": required_hits,
        "positive": {
            "total": len(pos_files),
            "recalled": sum(1 for s in pos_scores if s["score"] >= threshold),
            "recall": round(recall, 4),
            "min_score": min((s["score"] for s in pos_scores), default=0),
            "max_score": max((s["score"] for s in pos_scores), default=0),
            "scores": pos_scores,
        },
        "negative": {
            "total": len(neg_files),
            "false_wakes": sum(1 for s in neg_scores if s["score"] >= threshold),
            "false_wake_rate": round(false_wake, 4),
            "min_score": min((s["score"] for s in neg_scores), default=0),
            "max_score": max((s["score"] for s in neg_scores), default=0),
            "scores": neg_scores,
        },
        "approved": recall >= 0.95 and false_wake <= 0.01,
    }
    return results


def main():
    parser = argparse.ArgumentParser(description="Evaluate Leha wake-word model")
    parser.add_argument("--model", required=True, help="Path to ONNX model")
    parser.add_argument("--positive", required=True, help="Directory of positive held-out clips")
    parser.add_argument("--negative", required=True, help="Directory of negative held-out clips")
    parser.add_argument("--threshold", type=float, default=0.5, help="Wake threshold")
    parser.add_argument("--hop", type=float, default=0.25, help="Sliding window hop in seconds")
    parser.add_argument("--required-hits", type=int, default=1, help="Consecutive positive OWW frames required")
    parser.add_argument("--report", default=None, help="Write JSON report to this path")
    args = parser.parse_args()

    results = _evaluate_model(
        args.model,
        args.positive,
        args.negative,
        args.threshold,
        args.hop,
        required_hits=args.required_hits,
    )

    print(f"\n{'='*50}")
    print(f"  Wake Model Evaluation Report")
    print(f"{'='*50}")
    print(f"  Model:        {results['model']}")
    print(f"  Threshold:    {results['threshold']}")
    print(f"  Positives:    {results['positive']['recalled']}/{results['positive']['total']} "
          f"(recall={results['positive']['recall']:.1%})")
    print(f"  Negatives:    {results['negative']['false_wakes']}/{results['negative']['total']} "
          f"(false-wake={results['negative']['false_wake_rate']:.1%})")
    print(f"  Score range:  pos [{results['positive']['min_score']:.3f}, "
          f"{results['positive']['max_score']:.3f}]  neg [{results['negative']['min_score']:.3f}, "
          f"{results['negative']['max_score']:.3f}]")
    print(f"{'='*50}")

    if results["approved"]:
        print("  MODEL APPROVED")
    else:
        print("  MODEL NOT APPROVED")
        if results["positive"]["recall"] < 0.95:
            print(f"     -> Recall too low ({results['positive']['recall']:.1%} < 95%)")
        if results["negative"]["false_wake_rate"] > 0.01:
            print(f"     -> False-wake too high ({results['negative']['false_wake_rate']:.1%} > 1%)")
    print()

    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"[eval] Report -> {args.report}")

if __name__ == "__main__":
    main()
