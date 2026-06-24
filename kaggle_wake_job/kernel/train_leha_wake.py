"""Kaggle GPU job: train an experimental speaker-specific Leha wake model."""

from __future__ import annotations

import json
import random
import tarfile
import urllib.request
import wave
import zipfile
from pathlib import Path

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, Dataset


SEED = 42
RATE = 16_000
SAMPLES = RATE
WORK = Path("/kaggle/working")
INPUT = Path("/kaggle/input")
torch.manual_seed(SEED)
random.seed(SEED)
np.random.seed(SEED)


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as source:
        if source.getframerate() != RATE or source.getnchannels() != 1:
            raise ValueError(f"Expected mono 16 kHz WAV: {path}")
        audio = np.frombuffer(source.readframes(source.getnframes()), dtype=np.int16)
    return audio.astype(np.float32) / 32768.0


def fit(audio: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    audio = audio.copy()
    if len(audio) > SAMPLES:
        offset = int(rng.integers(0, len(audio) - SAMPLES + 1))
        audio = audio[offset:offset + SAMPLES]
    out = np.zeros(SAMPLES, dtype=np.float32)
    offset = int(rng.integers(0, max(1, SAMPLES - len(audio) + 1)))
    out[offset:offset + len(audio)] = audio
    return out


class WakeDataset(Dataset):
    def __init__(self, positives: list[np.ndarray], negatives: list[np.ndarray], n: int = 2400):
        self.positives, self.negatives, self.n = positives, negatives, n

    def __len__(self):
        return self.n

    def __getitem__(self, index):
        rng = np.random.default_rng(SEED + index)
        positive = index % 2 == 0
        pool = self.positives if positive else self.negatives
        audio = fit(pool[index % len(pool)], rng)
        if positive:
            audio *= float(rng.uniform(0.65, 1.35))
        else:
            audio *= float(rng.uniform(0.5, 1.2))
        audio += rng.normal(0.0, float(rng.uniform(0.001, 0.012)), SAMPLES).astype(np.float32)
        return torch.from_numpy(np.clip(audio, -1, 1))[None, :], torch.tensor(float(positive))


class WakeNet(nn.Module):
    def __init__(self):
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv1d(1, 16, 81, stride=4, padding=40), nn.ReLU(), nn.MaxPool1d(4),
            nn.Conv1d(16, 32, 21, stride=2, padding=10), nn.ReLU(), nn.MaxPool1d(4),
            nn.Conv1d(32, 48, 11, stride=2, padding=5), nn.ReLU(), nn.AdaptiveAvgPool1d(1),
        )
        self.classifier = nn.Linear(48, 1)

    def forward(self, audio):
        return self.classifier(self.features(audio).squeeze(-1)).squeeze(-1)


def load_negatives() -> list[np.ndarray]:
    private_paths = list(INPUT.rglob("negative/*.wav"))
    if private_paths:
        clips = [read_wav(path) for path in private_paths]
        print(f"Loaded {len(clips)} private negative clips", flush=True)
        return clips
    url = "https://storage.googleapis.com/download.tensorflow.org/data/mini_speech_commands.zip"
    archive = WORK / "mini_speech_commands.zip"
    extracted = WORK / "mini_speech_commands"
    try:
        print("Downloading public non-Leha speech for false-trigger training...", flush=True)
        urllib.request.urlretrieve(url, archive)
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(extracted)
        clips = [read_wav(path) for path in extracted.rglob("*.wav")]
        print(f"Loaded {len(clips)} public negative clips", flush=True)
        return clips
    except Exception as exc:
        raise RuntimeError(f"Negative speech download failed and no private negatives were supplied: {exc}")


def split(clips: list[np.ndarray], label: str) -> tuple[list[np.ndarray], list[np.ndarray]]:
    if len(clips) < 20:
        raise RuntimeError(f"Need at least 20 {label} clips, found {len(clips)}")
    ordered = list(clips)
    random.Random(SEED).shuffle(ordered)
    cut = max(1, int(len(ordered) * 0.8))
    return ordered[:cut], ordered[cut:]


def main():
    # Kaggle expands the uploaded archive into the mounted private dataset.
    positive_paths = list(INPUT.rglob("positive/*.wav"))
    if not positive_paths:
        raise RuntimeError("No private wake recordings were attached to this Kaggle job")
    positives = [read_wav(path) for path in positive_paths]
    negatives = load_negatives()
    train_positive, validation_positive = split(positives, "positive")
    train_negative, validation_negative = split(negatives, "negative")
    train = WakeDataset(train_positive, train_negative, n=2400)
    validation = WakeDataset(validation_positive, validation_negative, n=600)
    # Kaggle sometimes assigns a P100 while its preinstalled PyTorch only
    # supports newer CUDA architectures. CPU is slower but reliable for this
    # intentionally small wake-word model.
    device = torch.device("cpu")
    if torch.cuda.is_available() and torch.cuda.get_device_capability(0)[0] >= 7:
        device = torch.device("cuda")
    print(f"Training on {device}", flush=True)
    model = WakeNet().to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.001)
    loss_fn = nn.BCEWithLogitsLoss()
    for epoch in range(8):
        model.train()
        losses = []
        for audio, labels in DataLoader(train, batch_size=64, shuffle=True, num_workers=2):
            optimizer.zero_grad()
            loss = loss_fn(model(audio.to(device)), labels.to(device))
            loss.backward(); optimizer.step(); losses.append(float(loss))
        model.eval(); correct = total = 0
        with torch.no_grad():
            for audio, labels in DataLoader(validation, batch_size=128, num_workers=2):
                predicted = (torch.sigmoid(model(audio.to(device))) >= 0.5).cpu()
                correct += int((predicted == labels.bool()).sum())
                total += len(labels)
        print(f"epoch={epoch + 1} loss={np.mean(losses):.4f} validation_accuracy={correct/total:.3f}", flush=True)
    model.cpu().eval()
    sample = torch.zeros(1, 1, SAMPLES, dtype=torch.float32)
    output = WORK / "leha_wake_model.onnx"
    # Kaggle's current image omits onnxscript, required by the new exporter.
    # The legacy exporter is sufficient for this small Conv1D model.
    torch.onnx.export(
        model,
        sample,
        output,
        input_names=["audio"],
        output_names=["logit"],
        opset_version=17,
        dynamo=False,
    )
    (WORK / "leha_wake_metrics.json").write_text(json.dumps({
        "positive_clips": len(positives),
        "negative_clips": len(negatives),
        "validation_positive_clips": len(validation_positive),
        "validation_negative_clips": len(validation_negative),
        "rate": RATE,
    }, indent=2))
    print(f"Saved {output}", flush=True)


if __name__ == "__main__":
    main()
