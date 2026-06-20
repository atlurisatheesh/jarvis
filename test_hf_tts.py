"""Smoke-test Hugging Face TTS endpoint settings without starting Leha."""
from jarvis_ai import config
from jarvis_ai.mouth import Mouth

config.TTS_ENGINE = "hf"

print("HF_TTS_ENDPOINT_URL:", "set" if config.HF_TTS_ENDPOINT_URL else "not set")
print("HF_TTS_MODEL:", config.HF_TTS_MODEL or "not set")
print("HF_TOKEN:", "set" if config.HF_TOKEN else "not set")

mouth = Mouth()
mouth.say("Hello Sir, this is Leha using Hugging Face voice.", wait=True)
print("done")
