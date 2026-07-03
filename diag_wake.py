"""Diagnose wake word pipeline -- what's configured and why."""
import sys
sys.path.insert(0, r"D:\jarvis")

from jarvis_ai import wake_porcupine, wake_local_onnx, wake_openwakeword, config

print("=== WAKE WORD ENGINE STATUS ===\n")

# Porcupine
print(f"Porcupine available: {wake_porcupine.is_available()}")
print(f"  Access key present: {bool(getattr(config, 'PORCUPINE_ACCESS_KEY', '').strip())}")
print(f"  Keyword path: {getattr(config, 'PORCUPINE_KEYWORD_PATH', '')}")

# Local ONNX
print(f"\nLocal ONNX available: {wake_local_onnx.is_available()}")
print(f"  CUSTOM_WAKE_ENABLED: {getattr(config, 'CUSTOM_WAKE_ENABLED', False)}")
print(f"  Model path: {getattr(config, 'CUSTOM_WAKE_MODEL_PATH', '')}")
print(f"  Model exists: {__import__('os').path.isfile(getattr(config, 'CUSTOM_WAKE_MODEL_PATH', ''))}")
print(f"  Threshold: {getattr(config, 'CUSTOM_WAKE_THRESHOLD', 'default')}")

# openwakeword
print(f"\nopenwakeword available: {wake_openwakeword.is_available()}")
print(f"  OWW_ENABLED: {config.OWW_ENABLED}")

# Whisper fallback always there
print("\nWhisper fallback: ALWAYS available")

# Which engine will actually run?
print("\n=== RUNTIME ORDER (listen.py) ===")
order = []
if wake_porcupine.is_available():
    order.append("Porcupine")
if wake_local_onnx.is_available():
    order.append("Local ONNX")
if wake_openwakeword.is_available():
    order.append("openWakeWord")
order.append("Whisper fallback")
print(" -> ".join(order))

# Current strict mode
print(f"\nstrict_mode: {wake_phrases.strict_mode() if 'wake_phrases' in sys.modules else 'check wake_phrases.py'}"
      if False else "")
from jarvis_ai.wake_phrases import strict_mode
print(f"strict_mode: {strict_mode()}")
