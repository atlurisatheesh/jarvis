"""Audit Leha wake/negative audio clips before training.

The custom wake model is only as good as the recorded data. This tool rejects
silent/near-silent clips and produces a JSON report that can be used before
training or after recording new samples.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import soundfile as sf


def _stats(path: Path) -> dict:
    data, sr = sf.read(str(path), dtype="float32")
    if data.ndim > 1:
        data = data[:, 0]
    if len(data) == 0:
        return {"file": str(path), "sample_rate": sr, "seconds": 0.0, "rms": 0.0, "peak": 0.0}
    return {
        "file": str(path),
        "sample_rate": int(sr),
        "seconds": round(len(data) / float(sr), 3),
        "rms": float(np.sqrt(np.mean(data * data))),
        "peak": float(np.max(np.abs(data))),
    }


def audit(paths: list[Path], min_rms: float, min_peak: float, max_seconds: float) -> dict:
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files.extend(sorted(path.rglob("*.wav")))
        elif path.suffix.lower() == ".wav":
            files.append(path)

    rows = []
    rejected = []
    for path in sorted(set(files)):
        try:
            row = _stats(path)
        except Exception as exc:
            row = {"file": str(path), "error": str(exc), "accepted": False}
            rejected.append(row)
            rows.append(row)
            continue

        reasons = []
        if row["rms"] < min_rms:
            reasons.append("low_rms")
        if row["peak"] < min_peak:
            reasons.append("low_peak")
        if row["seconds"] <= 0:
            reasons.append("empty")
        if max_seconds > 0 and row["seconds"] > max_seconds:
            reasons.append("too_long")
        row["accepted"] = not reasons
        row["reasons"] = reasons
        rows.append(row)
        if reasons:
            rejected.append(row)

    accepted = [r for r in rows if r.get("accepted")]
    return {
        "total": len(rows),
        "accepted": len(accepted),
        "rejected": len(rejected),
        "min_rms": min_rms,
        "min_peak": min_peak,
        "max_seconds": max_seconds,
        "accepted_files": [r["file"] for r in accepted],
        "rejected_files": rejected,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit Leha wake-word WAV clips")
    parser.add_argument("paths", nargs="+", help="WAV files or directories")
    parser.add_argument("--min-rms", type=float, default=0.005)
    parser.add_argument("--min-peak", type=float, default=0.03)
    parser.add_argument("--max-seconds", type=float, default=4.0)
    parser.add_argument("--report", default="processed/wake_dataset_audit.json")
    args = parser.parse_args()

    result = audit([Path(p) for p in args.paths], args.min_rms, args.min_peak, args.max_seconds)
    report = Path(args.report)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("total", "accepted", "rejected")}, indent=2))
    print(f"[audit] Report -> {report}")
    if result["rejected"]:
        print("[audit] Rejected clips:")
        for row in result["rejected_files"][:25]:
            reasons = ",".join(row.get("reasons", ["error"]))
            print(f"  {Path(row['file']).name}: {reasons}")


if __name__ == "__main__":
    main()
