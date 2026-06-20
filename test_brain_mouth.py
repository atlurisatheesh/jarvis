import os
os.environ["PYTHONUNBUFFERED"] = "1"

from jarvis_ai.brain import Brain
from jarvis_ai.mouth import Mouth

def test_jarvis():
    print("Testing JARVIS Brain and Mouth (bypassing microphone)...")
    brain = Brain()
    mouth = Mouth()

    # Test 1: Simple TTS
    print("\n--- Test 1: Basic Speech ---")
    msg1 = "Testing output. If you hear this, TTS is working."
    print(f"Speaking: {msg1}")
    mouth.say(msg1)

    # Test 2: LLM + TTS
    print("\n--- Test 2: Brain + Speech ---")
    question = "What is 10 plus 15?"
    print(f"Asking Brain: {question}")
    reply = brain.ask(question)
    print(f"Brain replied: {reply}")
    print("Speaking brain reply...")
    mouth.say(reply)

    print("\nTest complete!")

if __name__ == "__main__":
    test_jarvis()
