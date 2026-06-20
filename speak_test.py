import pyttsx3
import time

engine = pyttsx3.init()
engine.setProperty('rate', 150)  # speaking rate

print("Synthesizing test phrase...")
text = "Jarvis, what is the capital of France?"
print(f"Saying: '{text}'")

engine.say(text)
engine.runAndWait()
print("Done speaking. Check JARVIS logs!")
