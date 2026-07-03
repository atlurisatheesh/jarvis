"""Wake-word model trainer.

Loads positive/negative WAV clips, trains a small CNN with PyTorch, and exports
to ONNX with a sigmoid output suitable for ``wake_local_onnx.LocalOnnxWakeListener``.

Data augmentation: Gaussian noise injection, speed perturbation (0.9×–1.1×),
random gain, time-shift.

Usage:
    python -m jarvis_ai.wake_trainer --positive ./voices/wake_leha --negative ./voices/wake_negative --output leha.onnx
    python -m jarvis_ai.wake_trainer --bundle processed/leha_wake_training_bundle.zip --output leha.onnx
"""
from __future__ import annotations

import argparse
import json
import os
import random
import zipfile
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Audio loading helpers
# ---------------------------------------------------------------------------

def _load_wav_16k(path: str | Path) -> np.ndarray:
    """Load a WAV file, resample to 16 kHz mono, return float32 array in [-1, 1]."""
    import io
    import soundfile as sf
    # Read the raw bytes ourselves and decode from memory so libsndfile never
    # holds an OS file handle. On Windows a lingering handle blocks the caller
    # from unlinking the file (WinError 32), even on the decode-failure path.
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
        data, sr = sf.read(io.BytesIO(raw), dtype="float32")
    except Exception:
        return None
    if data.ndim > 1:
        data = data[:, 0]  # mono
    if sr != 16000:
        from scipy.signal import resample_poly
        data = resample_poly(data, 16000, sr)
    # Normalise to [-1, 1]
    peak = np.max(np.abs(data))
    if peak > 0:
        data = data / peak
    return data


def _window(audio: np.ndarray, window_sec: float = 1.0, rate: int = 16000) -> np.ndarray:
    """Centre-crop or zero-pad to exactly ``window_sec`` seconds."""
    length = int(window_sec * rate)
    if len(audio) < length:
        padded = np.zeros(length, dtype=np.float32)
        start = (length - len(audio)) // 2
        padded[start : start + len(audio)] = audio
        return padded
    start = (len(audio) - length) // 2
    return audio[start : start + length].astype(np.float32)


# ---------------------------------------------------------------------------
# Data augmentation
# ---------------------------------------------------------------------------

def _augment(audio: np.ndarray, rate: int = 16000) -> np.ndarray:
    """Apply a random combination of augmentations."""
    aug = audio.copy()

    # Gain
    if random.random() < 0.5:
        gain = random.uniform(0.7, 1.3)
        aug = aug * gain

    # Noise injection
    if random.random() < 0.4:
        noise = np.random.randn(len(aug)).astype(np.float32) * random.uniform(0.002, 0.015)
        aug = aug + noise

    # Speed perturbation via resampling
    if random.random() < 0.3:
        factor = random.choice([0.9, 0.95, 1.05, 1.1])
        from scipy.signal import resample_poly
        aug = resample_poly(aug, int(factor * rate), rate)

    # Time shift
    if random.random() < 0.3:
        shift = random.randint(-int(0.1 * rate), int(0.1 * rate))
        aug = np.roll(aug, shift)

    return _window(aug.astype(np.float32))


# ---------------------------------------------------------------------------
# PyTorch model
# ---------------------------------------------------------------------------

def _build_model() -> "torch.nn.Module":
    """Build a small CNN for wake-word detection (1-second 16 kHz mono input)."""
    import torch
    import torch.nn as nn

    class WakeModel(nn.Module):
        """Tiny CNN: 5 conv layers → global avg pool → FC → sigmoid."""

        def __init__(self):
            super().__init__()
            self.features = nn.Sequential(
                nn.Conv1d(1, 16, kernel_size=7, stride=2, padding=3),   # 16k→8k
                nn.BatchNorm1d(16),
                nn.ReLU(),
                nn.Conv1d(16, 32, kernel_size=5, stride=2, padding=2),  # 8k→4k
                nn.BatchNorm1d(32),
                nn.ReLU(),
                nn.Conv1d(32, 64, kernel_size=5, stride=2, padding=2),  # 4k→2k
                nn.BatchNorm1d(64),
                nn.ReLU(),
                nn.Conv1d(64, 64, kernel_size=3, stride=2, padding=1),  # 2k→1k
                nn.BatchNorm1d(64),
                nn.ReLU(),
                nn.Conv1d(64, 64, kernel_size=3, stride=2, padding=1),  # 1k→500
                nn.BatchNorm1d(64),
                nn.ReLU(),
            )
            self.classifier = nn.Sequential(
                nn.AdaptiveAvgPool1d(1),
                nn.Flatten(),
                nn.Linear(64, 32),
                nn.ReLU(),
                nn.Linear(32, 1),
            )

        def forward(self, x: "torch.Tensor") -> "torch.Tensor":
            x = x.unsqueeze(1)  # (batch, 1, 16000)
            x = self.features(x)
            x = self.classifier(x)
            return x.squeeze(-1)  # (batch,)

    return WakeModel()


def _export_onnx(model: "torch.nn.Module", path: str | Path):
    """Export trained model to ONNX."""
    import torch
    model.eval()
    dummy = torch.randn(1, 16000)
    torch.onnx.export(
        model,
        dummy,
        str(path),
        input_names=["audio"],
        output_names=["logits"],
        dynamic_axes={"audio": {0: "batch"}, "logits": {0: "batch"}},
        opset_version=17,
    )
    print(f"[trainer] ONNX exported → {path}")


# ---------------------------------------------------------------------------
# Dataset helpers
# ---------------------------------------------------------------------------

def _load_clips_from_dirs(pos_dir: str, neg_dir: str, augment_factor: int = 3):
    """Load clips from positive/negative directories with augmentation."""
    positives = []
    negatives = []

    for f in sorted(Path(pos_dir).rglob("*.wav")):
        audio = _load_wav_16k(f)
        if audio is not None and len(audio) >= 8000:
            positives.append(_window(audio))

    for f in sorted(Path(neg_dir).rglob("*.wav")):
        audio = _load_wav_16k(f)
        if audio is not None and len(audio) >= 8000:
            negatives.append(_window(audio))

    print(f"[trainer] Loaded {len(positives)} positive, {len(negatives)} negative clips")

    # Augment positives to balance / increase data
    aug_pos = []
    for clip in positives:
        for _ in range(augment_factor):
            aug_pos.append(_augment(clip))

    all_pos = positives + aug_pos
    print(f"[trainer] After augmentation: {len(all_pos)} positive, {len(negatives)} negative")
    return all_pos, negatives


def _load_clips_from_bundle(zip_path: str, augment_factor: int = 3):
    """Load clips from a training bundle ZIP."""
    tmp = Path("processed/_bundle_tmp")
    tmp.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(tmp)
    pos_dir = tmp / "wake_leha_training" / "positive"
    neg_dir = tmp / "wake_leha_training" / "negative"
    result = _load_clips_from_dirs(str(pos_dir), str(neg_dir), augment_factor)
    # Cleanup
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    return result


# ---------------------------------------------------------------------------
# Training loop
# ---------------------------------------------------------------------------

def train(
    positives: list[np.ndarray],
    negatives: list[np.ndarray],
    epochs: int = 50,
    batch_size: int = 32,
    lr: float = 0.001,
    val_split: float = 0.15,
    output: str = "leha.onnx",
):
    """Train the wake model and export to ONNX."""
    import torch
    from torch.utils.data import DataLoader, TensorDataset, random_split

    # Balance dataset by oversampling negatives
    if len(negatives) < len(positives):
        mult = len(positives) // len(negatives) + 1
        negatives = negatives * mult

    random.shuffle(negatives)

    # Labels: 1 = wake, 0 = not wake
    X_pos = torch.tensor(np.array(positives), dtype=torch.float32)
    X_neg = torch.tensor(np.array(negatives[: len(positives)]), dtype=torch.float32)
    y_pos = torch.ones(len(positives), dtype=torch.float32)
    y_neg = torch.zeros(len(positives), dtype=torch.float32)

    X = torch.cat([X_pos, X_neg], dim=0)
    y = torch.cat([y_pos, y_neg], dim=0)

    dataset = TensorDataset(X, y)
    val_count = max(1, int(len(dataset) * val_split))
    train_count = len(dataset) - val_count
    train_ds, val_ds = random_split(dataset, [train_count, val_count])

    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(val_ds, batch_size=batch_size)

    model = _build_model()
    optimiser = torch.optim.Adam(model.parameters(), lr=lr)
    criterion = torch.nn.BCEWithLogitsLoss()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device)
    print(f"[trainer] Training on {device} for {epochs} epochs, batch={batch_size}")

    best_val_loss = float("inf")
    for epoch in range(1, epochs + 1):
        model.train()
        total_loss = 0.0
        for xb, yb in train_loader:
            xb, yb = xb.to(device), yb.to(device)
            logits = model(xb)
            loss = criterion(logits, yb)
            optimiser.zero_grad()
            loss.backward()
            optimiser.step()
            total_loss += loss.item() * len(xb)

        # Validation
        model.eval()
        val_loss = 0.0
        correct = 0
        total = 0
        with torch.no_grad():
            for xb, yb in val_loader:
                xb, yb = xb.to(device), yb.to(device)
                logits = model(xb)
                val_loss += criterion(logits, yb).item() * len(xb)
                preds = (torch.sigmoid(logits) >= 0.5).float()
                correct += (preds == yb).sum().item()
                total += len(yb)

        avg_train = total_loss / train_count
        avg_val = val_loss / val_count
        acc = correct / total if total > 0 else 0

        if (epoch % 5 == 0) or epoch == 1:
            print(f"[trainer] epoch {epoch:3d}  train={avg_train:.4f}  val={avg_val:.4f}  acc={acc:.3f}")

        if avg_val < best_val_loss:
            best_val_loss = avg_val
            _export_onnx(model, output)

    print(f"[trainer] Best val loss: {best_val_loss:.4f} → {output}")
    return output


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Train Leha wake-word model")
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--positive", help="Directory of positive wake clips")
    grp.add_argument("--bundle", help="Training bundle ZIP from prepare_leha_wake_training_bundle")
    parser.add_argument("--negative", help="Directory of negative clips")
    parser.add_argument("--output", default="leha.onnx", help="Output ONNX path")
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--lr", type=float, default=0.001)
    parser.add_argument("--augment", type=int, default=3, help="Augmentation multiplier for positives")
    args = parser.parse_args()

    if args.bundle:
        pos, neg = _load_clips_from_bundle(args.bundle, args.augment)
    else:
        pos, neg = _load_clips_from_dirs(args.positive, args.negative, args.augment)

    if len(pos) < 20:
        print("[trainer] ERROR: Need at least 20 positive clips")
        return
    if len(neg) < 50:
        print("[trainer] ERROR: Need at least 50 negative clips")
        return

    train(pos, neg, epochs=args.epochs, batch_size=args.batch_size, lr=args.lr, output=args.output)


if __name__ == "__main__":
    main()
