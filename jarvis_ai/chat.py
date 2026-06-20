"""Typed JARVIS — no microphone needed. Full brain + all 44 tools.

    python -m jarvis_ai.chat            (type, JARVIS types back)
    python -m jarvis_ai.chat --speak    (also speak replies aloud)

Use this when the mic isn't working, or any time you'd rather type.
"""
import sys

from . import config
from .brain import Brain


def main():
    speak = "--speak" in sys.argv
    brain = Brain()
    mouth = None
    if speak:
        from .mouth import Mouth
        mouth = Mouth()

    print(f"{config.ASSISTANT_NAME} ready (typed mode). Type a message, or 'quit'.\n")
    while True:
        try:
            text = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not text:
            continue
        if text.lower() in ("quit", "exit", "bye", "goodbye"):
            break
        reply = brain.ask(text)
        print(f"JARVIS: {reply}\n")
        if mouth:
            mouth.say(reply)
    print("JARVIS offline.")


if __name__ == "__main__":
    main()
