"""Build a simple Kaggle notebook wrapper around the script voice job."""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
KERNEL = ROOT / "kaggle_voice_job" / "kernel"


def main() -> None:
    script = (KERNEL / "leha_kaggle_voice_clone.py").read_text(encoding="utf-8")
    notebook = {
        "cells": [
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": script.splitlines(keepends=True),
            }
        ],
        "metadata": {
            "accelerator": "GPU",
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    (KERNEL / "leha_kaggle_voice_clone.ipynb").write_text(
        json.dumps(notebook, indent=1),
        encoding="utf-8",
    )
    metadata = json.loads((KERNEL / "kernel-metadata.json").read_text(encoding="utf-8"))
    metadata["id"] = "satheeshatluri/leha-gpu-voice-clone"
    metadata["title"] = "Leha GPU Voice Clone"
    metadata["code_file"] = "leha_kaggle_voice_clone.ipynb"
    metadata["kernel_type"] = "notebook"
    (KERNEL / "kernel-metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(KERNEL / "leha_kaggle_voice_clone.ipynb")


if __name__ == "__main__":
    main()
