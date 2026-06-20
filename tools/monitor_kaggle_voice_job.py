"""Monitor and download a Kaggle Leha voice-clone job.

Usage:
    python tools/monitor_kaggle_voice_job.py <owner/leha-gpu-voice-clone>
    python tools/monitor_kaggle_voice_job.py <owner/leha-gpu-voice-clone> --download
"""
from __future__ import annotations

import argparse
import subprocess
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "kaggle_voice_job" / "outputs"


def run(cmd: list[str]) -> str:
    result = subprocess.run(
        cmd,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("kernel", help="Kaggle kernel slug, for example owner/leha-gpu-voice-clone")
    parser.add_argument("--download", action="store_true", help="Download outputs when complete")
    parser.add_argument("--poll-seconds", type=int, default=60)
    args = parser.parse_args()

    while True:
        status = run(["kaggle", "kernels", "status", args.kernel])
        print(status, flush=True)
        low = status.lower()
        if any(word in low for word in ["complete", "error", "failed", "canceled", "cancelled"]):
            break
        time.sleep(args.poll_seconds)

    print("\nLatest logs:\n")
    try:
        print(run(["kaggle", "kernels", "logs", args.kernel]))
    except subprocess.CalledProcessError as e:
        print((e.stdout or "") + (e.stderr or ""))

    if args.download and "complete" in status.lower():
        OUT.mkdir(parents=True, exist_ok=True)
        print(run(["kaggle", "kernels", "output", args.kernel, "-p", str(OUT)]))
        print(f"Downloaded outputs to {OUT}")


if __name__ == "__main__":
    main()
