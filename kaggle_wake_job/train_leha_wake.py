"""Kaggle notebook script for GPU-accelerated wake-word training.

Designed to run in a Kaggle notebook with GPU. Downloads the training bundle
from the jarvis project, trains with augmentation on GPU, and exports ONNX.

Prerequisites in Kaggle:
    - Upload `leha_wake_training_bundle.zip` to the dataset or input
    - pip install torch onnxruntime soundfile scipy numpy

Usage in Kaggle notebook:
    %run kaggle_wake_job/train_leha_wake.py --bundle /kaggle/input/leha-wake-data/leha_wake_training_bundle.zip --output /kaggle/working/leha.onnx --epochs 100
"""
from __future__ import annotations

import sys
import os

# Add project root to path so we can import jarvis_ai modules
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from jarvis_ai.wake_trainer import train, _load_clips_from_bundle
import argparse


def main():
    parser = argparse.ArgumentParser(description="Kaggle GPU wake-word training")
    parser.add_argument("--bundle", required=True, help="Path to training bundle ZIP on Kaggle")
    parser.add_argument("--output", default="leha.onnx", help="Output ONNX path")
    parser.add_argument("--epochs", type=int, default=100, help="Training epochs (GPU allows more)")
    parser.add_argument("--batch-size", type=int, default=64, help="Batch size")
    parser.add_argument("--lr", type=float, default=0.001, help="Learning rate")
    parser.add_argument("--augment", type=int, default=5, help="Augmentation factor")
    args = parser.parse_args()

    import torch
    print(f"[kaggle] CUDA available: {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"[kaggle] GPU: {torch.cuda.get_device_name(0)}")

    pos, neg = _load_clips_from_bundle(args.bundle, augment_factor=args.augment)
    print(f"[kaggle] Training with {len(pos)} positive, {len(neg)} negative samples")

    train(
        positives=pos,
        negatives=neg,
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
        output=args.output,
    )
    print(f"[kaggle] Done! Download {args.output} from Kaggle working directory.")


if __name__ == "__main__":
    main()
