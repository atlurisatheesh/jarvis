"""JARVIS push-to-talk — the reliable voice mode (no wake word).

    python -m jarvis_ai.ptt

Press ENTER, speak your command, it transcribes -> answers -> speaks back.
Uses the proven native-rate capture path. Say 'quit' or Ctrl+C to exit.
"""
from . import config
from .audio import record_command
from .brain import Brain
from .ears import Ears
from .mouth import Mouth

_STOP = {"stop", "exit", "quit", "goodbye", "bye"}


def main():
    print("Loading JARVIS (push-to-talk)...")
    ears = Ears()
    brain = Brain()
    mouth = Mouth()
    mouth.say(f"{config.ASSISTANT_NAME} ready. Press enter, then speak.")
    while True:
        try:
            input("\n[Enter] then speak (Ctrl+C to quit) > ")
        except (EOFError, KeyboardInterrupt):
            break
        print("listening... (speak now)", flush=True)
        audio = record_command()
        text = ears.transcribe_int16(audio)
        print(f"You: {text}")
        if not text:
            mouth.say("I didn't catch that, Sir.")
            continue
        if text.lower().strip(" .!?") in _STOP:
            mouth.say("Goodbye, Sir.")
            break
        reply = brain.ask(text)
        mouth.say(reply)
    print("JARVIS offline.")


if __name__ == "__main__":
    main()
