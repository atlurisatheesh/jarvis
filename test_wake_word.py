#!/usr/bin/env python3
"""Test wake word detection without running the full Leha pipeline.

Usage:
    python test_wake_word.py          -> record 3s and test trigger matching
    python test_wake_word.py --loop   -> continuous listen mode (ctrl+c to stop)
    python test_wake_word.py --text "..." -> test your trigger against the engine
"""
from __future__ import annotations
import sys
import time
from unittest.mock import patch

sys.path.insert(0, r"D:\jarvis")

from jarvis_ai import config, wake_phrases, wake_local_onnx, wake_porcupine


def test_openwakeword_skips_model_with_missing_external_weights(tmp_path):
    from jarvis_ai import wake_openwakeword

    graph = tmp_path / "hey_leha.onnx"
    graph.write_bytes(b"graph only")
    missing = str(tmp_path / "hey_leha.onnx.data")
    with patch.object(config, "OWW_CUSTOM_MODELS", [str(graph)]), \
         patch.object(config, "OWW_MODEL_PATH", ""), \
         patch.object(wake_openwakeword, "_missing_external_data", return_value=[missing]):
        assert wake_openwakeword._resolve_custom_models() == []
from jarvis_ai.audio import resolve_device


def analyze_trigger_matching(text: str) -> dict:
    """Return detailed trigger match info for a piece of text."""
    result = {
        "raw": text,
        "normalized": wake_phrases.normalize_text(text),
        "strict_mode": wake_phrases.strict_mode(),
        "has_trigger": wake_phrases.has_trigger(text),
        "is_hallucination": wake_phrases.is_hallucination(text),
        "wake_confidence": wake_phrases.wake_confidence(text),
        "stripped": wake_phrases.strip_trigger(text),
    }
    return result


def test_microphone_once():
    """Record 3 seconds and show what the STT engine hears."""
    import sounddevice as sd
    import numpy as np
    from jarvis_ai.ears import Ears
    from jarvis_ai.audio import record_command

    print("Recording 3 seconds... (say 'Leha <command>' now)")
    audio = record_command(max_seconds=3, silence_ms=900)
    print(f"Captured {len(audio)} samples")

    if len(audio) == 0:
        print("No audio captured. Check your mic.")
        return

    ears = Ears()
    text = ears.transcribe_int16(audio).strip()
    print(f"\nSTT heard: '{text}'")

    info = analyze_trigger_matching(text)
    print("\nTrigger analysis:")
    for k, v in info.items():
        print(f"  {k}: {v}")

    if info["has_trigger"] and not info["is_hallucination"]:
        print("\n  WAKE WORD DETECTED!")
    else:
        print("\n  WAKE WORD NOT DETECTED")


def live_wake_loop():
    """Listen continuously and print trigger detection.

    Uses the same audio pipeline as the real listener but without the brain.
    """
    import sounddevice as sd
    import numpy as np
    from jarvis_ai.audio import stream_utterances
    from jarvis_ai.ears import Ears
    from jarvis_ai.mouth import Mouth

    print("\n=== LIVE WAKE TEST ===")
    print("Say 'Leha <command>' or just speak to see what STT hears.\n")

    ears = Ears()
    mic_dev = resolve_device(config.MIC_DEVICE)
    print(f"Mic device: {mic_dev}")
    print(f"strict_mode: {wake_phrases.strict_mode()}")
    print("-" * 40)
    print()

    for audio in stream_utterances(
        should_mute=lambda: False,
        silence_ms=350,
        max_seconds=12,
        min_samples=6000,
    ):
        text = ears.transcribe_int16(audio).strip()
        if not text:
            continue

        info = analyze_trigger_matching(text)
        woke = info["has_trigger"] and not info["is_hallucination"]

        if woke:
            print(f"[WAKE]  '{text}' (conf={info['wake_confidence']:.2f})")
            command = info["stripped"]
            if command:
                print(f"[CMD]   '{command}'")
        else:
            print(f"[idle]  '{text}' | conf={info['wake_confidence']:.2f} "
                  f"mode={'strict' if info['strict_mode'] else 'broad'}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Test Leha wake word detection")
    parser.add_argument("--text", help="Test a specific text string")
    parser.add_argument("--loop", action="store_true", help="Run continuous listen loop")
    args = parser.parse_args()

    if args.text:
        print(f"Testing: '{args.text}'")
        info = analyze_trigger_matching(args.text)
        for k, v in info.items():
            print(f"  {k}: {v}")
    elif args.loop:
        live_wake_loop()
    else:
        test_microphone_once()


def test_telugu_script_wake_trigger():
    text = "\u0c32\u0c47\u0c39\u0c3e \u0c24\u0c46\u0c32\u0c41\u0c17\u0c41\u0c32\u0c4b \u0c12\u0c15 \u0c2a\u0c3e\u0c1f \u0c2a\u0c3e\u0c21\u0c41"
    info = analyze_trigger_matching(text)

    assert info["has_trigger"]
    assert "\u0c2a\u0c3e\u0c1f" in info["stripped"]


def test_lehan_observed_variant_wakes():
    info = analyze_trigger_matching("Lehan sing a song")

    assert info["has_trigger"]


def test_lehrer_observed_variant_wakes():
    info = analyze_trigger_matching("Lehrer sing a song")

    assert info["has_trigger"]


def test_greek_leha_transliteration_observed_in_live_log_wakes():
    assert analyze_trigger_matching("Σλέχα")["has_trigger"]
    assert analyze_trigger_matching("λέχα")["has_trigger"]


if __name__ == "__main__":
    main()
