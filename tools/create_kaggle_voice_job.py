"""Create a private Kaggle GPU voice-clone job for Leha.

This script prepares and optionally pushes:
1. A private Kaggle dataset containing the voice reference bundle.
2. A Kaggle notebook that generates Chatterbox cloned voice samples on GPU.

It intentionally does not store Kaggle tokens. Authenticate with Kaggle's
`KAGGLE_API_TOKEN` environment variable or your local Kaggle config.

Usage:
    python tools/create_kaggle_voice_job.py --prepare-only
    python tools/create_kaggle_voice_job.py --push
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "kaggle_voice_job"
DATASET_DIR = BUILD / "dataset"
KERNEL_DIR = BUILD / "kernel"
VOICE_BUNDLE = ROOT / "voice_gpu_bundle.zip"

DATASET_SLUG = "leha-private-voice-reference"
KERNEL_SLUG = "leha-gpu-voice-clone"


def run(cmd: list[str], cwd: Path | None = None) -> str:
    result = subprocess.run(
        cmd,
        cwd=str(cwd or ROOT),
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def kaggle_username() -> str:
    out = run(["kaggle", "config", "view"])
    for line in out.splitlines():
        if line.strip().startswith("- username:"):
            return line.split(":", 1)[1].strip()
    raise RuntimeError("Could not read Kaggle username. Run `kaggle config view`.")


def prepare() -> tuple[str, str]:
    username = kaggle_username()
    if not VOICE_BUNDLE.exists():
        run(["python", "tools/prepare_voice_gpu_bundle.py"])

    if BUILD.exists():
        shutil.rmtree(BUILD)
    DATASET_DIR.mkdir(parents=True)
    KERNEL_DIR.mkdir(parents=True)

    shutil.copy2(VOICE_BUNDLE, DATASET_DIR / "voice_gpu_bundle.zip")
    (DATASET_DIR / "dataset-metadata.json").write_text(
        json.dumps(
            {
                "title": "Leha Private Voice Reference",
                "id": f"{username}/{DATASET_SLUG}",
                "licenses": [{"name": "CC0-1.0"}],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    source = (ROOT / "notebooks/leha_chatterbox_gpu_colab.ipynb").read_text(encoding="utf-8")
    notebook = json.loads(source)
    notebook["metadata"]["kaggle"] = {
        "accelerator": "gpu",
        "dataSources": [f"{username}/{DATASET_SLUG}"],
        "dockerImageVersionId": 30786,
        "isGpuEnabled": True,
        "isInternetEnabled": True,
        "language": "python",
        "sourceType": "notebook",
    }
    (KERNEL_DIR / "leha_chatterbox_gpu_colab.ipynb").write_text(
        json.dumps(notebook, indent=1),
        encoding="utf-8",
    )
    (KERNEL_DIR / "kernel-metadata.json").write_text(
        json.dumps(
            {
                "id": f"{username}/{KERNEL_SLUG}",
                "title": "Leha GPU Voice Clone",
                "code_file": "leha_chatterbox_gpu_colab.ipynb",
                "language": "python",
                "kernel_type": "notebook",
                "is_private": True,
                "enable_gpu": True,
                "enable_internet": True,
                "dataset_sources": [f"{username}/{DATASET_SLUG}"],
                "competition_sources": [],
                "kernel_sources": [],
                "model_sources": [],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return f"{username}/{DATASET_SLUG}", f"{username}/{KERNEL_SLUG}"


def push(dataset: str, kernel: str) -> None:
    print("Creating private Kaggle dataset...")
    try:
        print(run(["kaggle", "datasets", "create", "-p", str(DATASET_DIR), "-r", "zip"]))
    except subprocess.CalledProcessError as e:
        text = (e.stdout or "") + "\n" + (e.stderr or "")
        if "already exists" in text.lower() or "slug" in text.lower():
            print("Dataset may already exist; creating a new private dataset version...")
            print(run(["kaggle", "datasets", "version", "-p", str(DATASET_DIR), "-m", "Update Leha voice reference bundle", "-r", "zip"]))
        else:
            raise

    print("Pushing Kaggle GPU notebook...")
    print(run(["kaggle", "kernels", "push", "-p", str(KERNEL_DIR), "--accelerator", "gpu", "--timeout", "7200"]))
    print(f"Kernel: {kernel}")
    print("Monitor with:")
    print(f"  python tools/monitor_kaggle_voice_job.py {kernel}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--push", action="store_true")
    args = parser.parse_args()

    dataset, kernel = prepare()
    print(f"Prepared Kaggle dataset folder: {DATASET_DIR}")
    print(f"Prepared Kaggle kernel folder:  {KERNEL_DIR}")
    print(f"Dataset target: {dataset}")
    print(f"Kernel target:  {kernel}")
    if args.push:
        push(dataset, kernel)
    elif not args.prepare_only:
        print("Dry run only. Add --push to upload and run the private GPU notebook.")


if __name__ == "__main__":
    main()
