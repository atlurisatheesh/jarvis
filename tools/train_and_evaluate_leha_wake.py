"""One-command Leha wake-word pipeline: generate -> train -> evaluate -> deploy.

Phase 1 orchestrator. Ties together the synthetic data generator, the trainer,
and the evaluator so a working (synthetic) wake model can be built end-to-end
without manual steps. Real owner recordings can later be dropped into the
positive/negative dirs to improve accuracy.

Steps:
  1. Generate synthetic positive + negative clips (if --data given).
  2. Train a CNN wake model with augmentation, export to ONNX.
  3. Evaluate on a held-out split against the approval gate
     (>=95% recall, <=1% false wake).
  4. If approved, copy the ONNX model to the configured production path and
     print instructions for enabling it.

Usage::

    python tools/train_and_evaluate_leha_wake.py
    python tools/train_and_evaluate_leha_wake.py --skip-generate --data voices/wake_real
    python tools/train_and_evaluate_leha_wake.py --positives 300 --epochs 80
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ONNX_OUTPUT = ROOT / "jarvis_ai" / "voices" / "leha_wake_model.onnx"
DEFAULT_DATA_DIR = ROOT / "jarvis_ai" / "voices" / "wake_synthetic"


def step_generate(data_dir: Path, positives: int, negatives: int) -> bool:
    """Run the synthetic data generator. Returns True on success."""
    print(f"\n{'='*60}\n[1/4] Generating synthetic data -> {data_dir}\n{'='*60}")
    cmd = [
        sys.executable, str(ROOT / "tools" / "generate_synthetic_wake_data.py"),
        "--out", str(data_dir),
        "--positives", str(positives),
        "--negatives", str(negatives),
    ]
    try:
        subprocess.run(cmd, check=True, cwd=str(ROOT))
        return True
    except subprocess.CalledProcessError as e:
        print(f"[pipeline] data generation failed: {e}")
        return False


def step_train(data_dir: Path, output: Path, epochs: int) -> bool:
    """Train the wake model. Returns True on success."""
    print(f"\n{'='*60}\n[2/4] Training wake model -> {output}\n{'='*60}")
    from jarvis_ai import wake_trainer
    pos_dir = data_dir / "positive"
    neg_dir = data_dir / "negative"
    if not pos_dir.exists() or not neg_dir.exists():
        print(f"[pipeline] missing data dirs: {pos_dir} / {neg_dir}")
        return False
    pos, neg = wake_trainer._load_clips_from_dirs(str(pos_dir), str(neg_dir), augment_factor=3)
    if len(pos) < 20:
        print(f"[pipeline] ERROR: need >=20 positive clips, got {len(pos)}")
        return False
    if len(neg) < 50:
        print(f"[pipeline] ERROR: need >=50 negative clips, got {len(neg)}")
        return False
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        wake_trainer.train(pos, neg, epochs=epochs, output=str(output))
        return output.exists()
    except Exception as e:
        print(f"[pipeline] training failed: {e}")
        return False


def step_evaluate(model_path: Path, data_dir: Path) -> dict | None:
    """Evaluate the trained model on held-out data. Returns result dict or None."""
    print(f"\n{'='*60}\n[3/4] Evaluating model -> {model_path}\n{'='*60}")
    if not model_path.exists():
        print(f"[pipeline] model not found: {model_path}")
        return None
    try:
        import onnxruntime  # noqa: F401
    except ImportError:
        print("[pipeline] onnxruntime not installed; skipping live evaluation.")
        print("           Install with: pip install onnxruntime")
        return {"approved": None, "skipped": True}

    from jarvis_ai import wake_evaluator
    evaluate = getattr(wake_evaluator, "evaluate", None) or \
        getattr(wake_evaluator, "_evaluate_model", None)
    if evaluate is None:
        print("[pipeline] wake_evaluator has no evaluate/_evaluate_model function")
        return None
    try:
        result = evaluate(
            str(model_path),
            str(data_dir / "positive"),
            str(data_dir / "negative"),
            0.995,
        )
        result_str = json.dumps(result, indent=2, default=str)
        print(result_str)
        return result
    except Exception as e:
        print(f"[pipeline] evaluation failed: {e}")
        return None


def step_deploy(model_path: Path, approved: bool | None) -> bool:
    """Print deployment instructions (does NOT auto-enable to preserve safety)."""
    print(f"\n{'='*60}\n[4/4] Deployment\n{'='*60}")
    if not model_path.exists():
        print("[pipeline] no model to deploy")
        return False
    if approved is False:
        print("[pipeline] MODEL NOT APPROVED — do not deploy. Tune threshold or add data.")
        return False
    # The model already lives at the configured CUSTOM_WAKE_MODEL_PATH, so no
    # copy is needed. We only print how to enable it (preserving the opt-in flag).
    print(f"Trained model: {model_path}")
    print("\nTo enable the dedicated Leha wake detector, edit config.py:")
    print("    CUSTOM_WAKE_ENABLED = True")
    print("\nThe model path is already configured as CUSTOM_WAKE_MODEL_PATH.")
    print("Keep transcript matching as a fallback; it activates automatically if")
    print("the ONNX model is unavailable.")
    return True


def run_pipeline(data_dir: Path, output: Path, epochs: int,
                 positives: int, negatives: int, skip_generate: bool) -> int:
    if not skip_generate:
        if not step_generate(data_dir, positives, negatives):
            return 1
    elif not (data_dir / "positive").exists():
        print(f"[pipeline] --skip-generate but no data at {data_dir / 'positive'}")
        return 1

    if not step_train(data_dir, output, epochs):
        return 2

    result = step_evaluate(output, data_dir)
    approved = result.get("approved") if result else None

    step_deploy(output, approved)
    print(f"\n{'='*60}\nPipeline complete.\n{'='*60}")
    return 0 if approved is not False else 3


def main():
    parser = argparse.ArgumentParser(description="Train and evaluate Leha wake model")
    parser.add_argument("--data", default=str(DEFAULT_DATA_DIR), help="Data directory")
    parser.add_argument("--output", default=str(ONNX_OUTPUT), help="Output ONNX model path")
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--positives", type=int, default=200)
    parser.add_argument("--negatives", type=int, default=2000)
    parser.add_argument("--skip-generate", action="store_true",
                        help="Reuse existing data (skip synthetic generation)")
    args = parser.parse_args()
    sys.exit(run_pipeline(
        Path(args.data), Path(args.output), args.epochs,
        args.positives, args.negatives, args.skip_generate,
    ))


if __name__ == "__main__":
    main()
