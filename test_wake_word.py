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

sys.path.insert(0, r"D:\jarvis")

from jarvis_ai import config, wake_phrases, wake_local_onnx, wake_porcupine
from jarvis_ai.audio import resolve_device


def test_trigger_matching(text: str) -> dict:
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

    info = test_trigger_matching(text)
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

        info = test_trigger_matching(text)
        woke = info["has_trigger"] and not info["is_hallucination"]

        if woke:
            print(f"[WAKE]  '{text}' (conf={info['wake_confidence']:.2f})")
            command = info["stripped"]
            if command:
                print(f"[CMD]   '{command}'")
        else:
            print(f"[idle]  '{text.ct}' | conf={info['wake_confidence']:.2f} "
                  f"mode={'strict' if info['strict_mode'] else 'broad'}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Test Leha wake word detection")
    parser.add_argument("--text", help="Test a specific text string")
    parser.add_argument("--loop", action="store_true", help="Run continuous listen loop")
    args = parser.parse_args()

    if args.text:
        print(f"Testing: '{args.text}'")
        info = test_trigger_matching(args.text)
        for k, v in info.items():
            print(f"  {k}: {v}")
    elif args.loop:
        live_wake_loop()
    else:
        test_microphone_once()


if __name__ == "__main__":
    main()
