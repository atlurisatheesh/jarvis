"""Pre-flight check. Run:  python setup_check.py"""
import importlib
import sys


def check_imports():
    mods = ["faster_whisper", "openwakeword", "sounddevice", "numpy",
            "soundfile", "ollama", "psutil", "pyautogui", "pyttsx3"]
    ok = True
    for m in mods:
        try:
            importlib.import_module(m)
            print(f"  [ok] {m}")
        except Exception as e:
            ok = False
            print(f"  [MISSING] {m}: {e}")
    return ok


def check_ollama():
    try:
        import ollama
        from jarvis_ai import config
        client = ollama.Client(host=config.OLLAMA_HOST)
        names = [m["model"] for m in client.list().get("models", [])]
        print(f"  [ok] Ollama reachable. Models: {names or 'none pulled yet'}")
        if not any(config.BRAIN_MODEL.split(':')[0] in n for n in names):
            print(f"  [todo] pull the brain:  ollama pull {config.BRAIN_MODEL}")
        return True
    except Exception as e:
        print(f"  [FAIL] Ollama not reachable: {e}")
        print("        Install from ollama.com and make sure it is running.")
        return False


def check_mic():
    try:
        import sounddevice as sd
        ins = [d["name"] for d in sd.query_devices() if d["max_input_channels"] > 0]
        print(f"  [ok] Input devices: {ins[:3] or 'NONE FOUND'}")
        return bool(ins)
    except Exception as e:
        print(f"  [FAIL] mic query: {e}")
        return False


if __name__ == "__main__":
    print("== Python packages ==")
    a = check_imports()
    print("== Ollama brain ==")
    b = check_ollama()
    print("== Microphone ==")
    c = check_mic()
    print("\nResult:", "ALL GOOD - run: python -m jarvis_ai.main"
          if (a and b and c) else "fix the items above first")
    sys.exit(0 if (a and b and c) else 1)
