"""Health diagnostics for Leha subsystems.

    python -m jarvis_ai.health        # human-readable
    python -m jarvis_ai.health --json # machine-readable

Checks: brain (Ollama + Groq), ears (Deepgram/OpenAI/Groq keys), mic devices,
phone (ADB), Google OAuth token, and internet. Read-only — runs nothing
destructive.
"""
import json
import socket

from . import config


def _ok(cond): return "ok" if cond else "missing"


def check() -> dict:
    r: dict = {}

    # --- network ---
    try:
        socket.create_connection(("1.1.1.1", 53), timeout=3).close()
        r["internet"] = "ok"
    except Exception:
        r["internet"] = "down"

    # --- brain: Ollama up? ---
    try:
        import requests
        resp = requests.get(f"{config.OLLAMA_HOST}/api/tags", timeout=3)
        models = [m.get("name", "") for m in resp.json().get("models", [])]
        r["ollama"] = "ok" if resp.ok else "down"
        r["ollama_has_model"] = _ok(any(config.BRAIN_MODEL.split(":")[0] in m for m in models))
    except Exception:
        r["ollama"] = "down"; r["ollama_has_model"] = "unknown"
    r["groq_key"] = _ok(bool(config.GROQ_API_KEY))
    r["cloudflare"] = _ok(bool(
        getattr(config, "CF_BRAIN_ENABLED", False)
        and config.CLOUDFLARE_ACCOUNT_ID
        and config.CLOUDFLARE_API_TOKEN
    ))
    r["brain_engine"] = config.BRAIN_ENGINE

    # --- ears ---
    r["deepgram_key"] = _ok(bool(config.DEEPGRAM_API_KEY))
    r["openai_key"] = _ok(bool(config.OPENAI_API_KEY))
    r["stt_engine"] = config.STT_ENGINE

    # --- mic ---
    try:
        import sounddevice as sd
        ins = [d for d in sd.query_devices() if d["max_input_channels"] > 0]
        r["mic_inputs"] = len(ins)
        configured = config.MIC_DEVICE
        if isinstance(configured, int):
            devices = sd.query_devices()
            valid = 0 <= configured < len(devices) and devices[configured]["max_input_channels"] > 0
        elif configured:
            valid = any(str(configured).lower() in d["name"].lower() for d in ins)
        else:
            valid = bool(ins)
        r["mic_configured"] = _ok(valid)
    except Exception as e:
        r["mic_inputs"] = 0; r["mic_configured"] = f"error: {e}"

    # --- phone (ADB) ---
    try:
        import subprocess
        out = subprocess.run([config.ADB_PATH, "devices"], capture_output=True,
                             text=True, timeout=8).stdout
        devices = [ln for ln in out.splitlines()[1:] if ln.strip().endswith("device")]
        r["phone_adb"] = "ok" if devices else "no device"
    except Exception:
        r["phone_adb"] = "adb missing"

    # --- Google OAuth token present ---
    try:
        from pathlib import Path
        r["google_token"] = _ok(Path(config.GOOGLE_TOKEN_FILE).exists())
    except Exception:
        r["google_token"] = "unknown"

    return r


def voice_summary() -> str:
    """Short spoken diagnostic; deliberately avoids tokens and private data."""
    r = check()
    from .runtime_state import runtime

    state = runtime.snapshot()
    ears = r["deepgram_key"] == "ok" or r["openai_key"] == "ok" or r["groq_key"] == "ok"
    brain = "ready" if any(r[name] == "ok" for name in ("groq_key", "openai_key", "ollama")) else "unavailable"
    mic = "ready" if r["mic_configured"] == "ok" else "needs attention"
    timings = state.get("timings_ms", {})
    provider = state.get("last_provider") or "not measured yet"
    timing_text = ""
    if timings:
        total = timings.get("turn_dispatch") or timings.get("brain")
        if total is not None:
            timing_text = f" Last provider {provider}, {round(float(total))} milliseconds."
    return f"Health: microphone {mic}, ears {'ready' if ears else 'unavailable'}, brain {brain}, state {state['state']}.{timing_text}"


def summary() -> str:
    r = check()
    lines = [f"{k:18s}: {v}" for k, v in r.items()]
    return "Leha health:\n" + "\n".join(lines)


def main():
    import sys
    if "--json" in sys.argv:
        print(json.dumps(check(), indent=2))
    else:
        print(summary())


if __name__ == "__main__":
    main()
