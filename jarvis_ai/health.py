"""Health diagnostics for Leha subsystems.

    python -m jarvis_ai.health        # human-readable
    python -m jarvis_ai.health --json # machine-readable

Checks: brain (Ollama + Groq), ears (Deepgram/OpenAI/Groq keys), mic devices,
phone (ADB), Google OAuth token, and internet. Read-only — runs nothing
destructive.
"""
import json
import queue
import socket
import time

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
    r["cloudflare_model"] = getattr(config, "CF_BRAIN_MODEL", "")
    r["sarvam_ai"] = _ok(bool(
        getattr(config, "SARVAM_AI_ENABLED", False)
        and getattr(config, "SARVAM_API_KEY", "")
    ))
    r["sarvam_ai_model"] = getattr(config, "SARVAM_CHAT_MODEL", "")
    r["brain_engine"] = config.BRAIN_ENGINE

    # --- ears ---
    r["deepgram_key"] = _ok(bool(config.DEEPGRAM_API_KEY))
    r["openai_key"] = _ok(bool(config.OPENAI_API_KEY))
    r["stt_engine"] = config.STT_ENGINE

    # --- wake engine ---
    try:
        from . import wake_porcupine, wake_local_onnx, wake_openwakeword
        if wake_porcupine.is_available():
            r["wake_engine"] = "porcupine"
            r["wake_reliable"] = "ok"
        elif wake_local_onnx.is_available():
            r["wake_engine"] = "local_onnx"
            r["wake_reliable"] = "ok"
        elif wake_openwakeword.is_available():
            hybrid = bool(getattr(config, "OWW_HYBRID_TRANSCRIPT_FALLBACK", False))
            r["wake_engine"] = "openwakeword+strict_transcript" if hybrid else "openwakeword"
            # Hybrid is safer and faster than transcript-only, but still needs
            # a human room test before it can be called fully validated.
            r["wake_reliable"] = "hybrid" if hybrid else "ok"
        else:
            strict = bool(getattr(config, "TRANSCRIPT_WAKE_STRICT", True))
            r["wake_engine"] = "strict_transcript" if strict else "whisper_fallback"
            r["wake_reliable"] = "limited" if strict else "missing"
    except Exception as e:
        r["wake_engine"] = f"error: {e}"
        r["wake_reliable"] = "missing"

    # --- mic ---
    try:
        import sounddevice as sd
        from .audio import resolve_device
        ins = [d for d in sd.query_devices() if d["max_input_channels"] > 0]
        r["mic_inputs"] = len(ins)
        configured = config.MIC_DEVICE
        resolved = resolve_device(configured)
        r["mic_configured"] = _ok(resolved is not None)
        r["mic_resolved_index"] = resolved if resolved is not None else "none"
        if resolved is not None:
            try:
                r["mic_resolved_name"] = sd.query_devices(resolved)["name"]
            except Exception:
                r["mic_resolved_name"] = "unknown"
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


def mic_self_test(seconds: float | None = None) -> dict:
    """Open the resolved microphone briefly and report RMS.

    Read-only audio diagnostic; it does not transcribe or store audio.
    """
    seconds = float(seconds if seconds is not None else getattr(config, "MIC_SELF_TEST_SECONDS", 0.25))
    try:
        import numpy as np
        import sounddevice as sd
        from .audio import resolve_device, _capture_rates
        dev = resolve_device(config.MIC_DEVICE)
        if dev is None:
            return {"ok": False, "device": "none", "error": "no input device"}
        native = _capture_rates(dev)[-1]
        block = max(160, int(native * 0.05))
        q: queue.Queue = queue.Queue()

        def cb(indata, frames, t, s):
            q.put(indata.copy())

        with sd.InputStream(samplerate=native, channels=1, blocksize=block,
                            dtype="int16", device=dev, callback=cb):
            chunks = []
            for _ in range(max(1, int(seconds * native / block))):
                chunks.append(q.get(timeout=1.0).flatten().astype(np.float32))
        audio = np.concatenate(chunks) if chunks else np.zeros(1, dtype=np.float32)
        rms = float(np.sqrt(np.mean(audio ** 2)))
        return {"ok": True, "device": dev, "sample_rate": native, "rms": round(rms, 1)}
    except Exception as e:
        return {"ok": False, "device": getattr(config, "MIC_DEVICE", None), "error": str(e)}


def cloudflare_probe() -> dict:
    """Probe the configured Cloudflare model with a tiny request.

    This is separate from ``check()`` because it consumes provider quota. Use it
    only when actively validating the cloud brain.
    """
    if not (
        getattr(config, "CF_BRAIN_ENABLED", False)
        and config.CLOUDFLARE_ACCOUNT_ID
        and config.CLOUDFLARE_API_TOKEN
    ):
        return {"ok": False, "status": "missing_credentials", "model": getattr(config, "CF_BRAIN_MODEL", "")}
    try:
        import requests

        url = (
            f"https://api.cloudflare.com/client/v4/accounts/"
            f"{config.CLOUDFLARE_ACCOUNT_ID}/ai/v1/chat/completions"
        )
        payload = {
            "model": config.CF_BRAIN_MODEL,
            "messages": [
                {"role": "system", "content": "Reply in exactly two words."},
                {"role": "user", "content": "Say ready."},
            ],
            "max_tokens": 8,
        }
        start = time.perf_counter()
        response = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {config.CLOUDFLARE_API_TOKEN}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=config.CF_BRAIN_TIMEOUT_SECONDS,
        )
        latency_ms = round((time.perf_counter() - start) * 1000)
        if response.ok:
            data = response.json()
            reply = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
            )
            return {
                "ok": True,
                "status": "ok",
                "model": config.CF_BRAIN_MODEL,
                "latency_ms": latency_ms,
                "reply": reply[:80],
            }
        text = response.text[:300]
        status = "error"
        if response.status_code == 429:
            status = "quota_or_rate_limited"
        elif response.status_code in {401, 403}:
            status = "auth_failed"
        return {
            "ok": False,
            "status": status,
            "http_status": response.status_code,
            "model": config.CF_BRAIN_MODEL,
            "latency_ms": latency_ms,
            "error": text,
        }
    except Exception as e:
        return {
            "ok": False,
            "status": "exception",
            "model": getattr(config, "CF_BRAIN_MODEL", ""),
            "error": str(e),
        }


def startup_gate() -> tuple[bool, list[str]]:
    """Return whether startup has the minimum pieces for a useful assistant."""
    if not getattr(config, "STARTUP_HEALTH_GATE_ENABLED", True):
        return True, []
    status = check()
    issues: list[str] = []

    mic = mic_self_test()
    if "mic" in getattr(config, "STARTUP_HEALTH_REQUIRED", {"mic"}):
        if status.get("mic_configured") != "ok" or not mic.get("ok"):
            issues.append("microphone")

    if "ears" in getattr(config, "STARTUP_HEALTH_REQUIRED", {"ears"}):
        ears_ready = any(status.get(k) == "ok" for k in ("deepgram_key", "openai_key", "groq_key"))
        if not ears_ready:
            issues.append("speech recognition")

    if "brain" in getattr(config, "STARTUP_HEALTH_REQUIRED", {"brain"}):
        brain_ready = any(status.get(k) == "ok" for k in ("cloudflare", "sarvam_ai", "groq_key", "openai_key", "ollama"))
        if not brain_ready:
            issues.append("brain")

    return not issues, issues


def voice_summary() -> str:
    """Short spoken diagnostic; deliberately avoids tokens and private data."""
    r = check()
    from .runtime_state import runtime

    state = runtime.snapshot()
    ears = r["deepgram_key"] == "ok" or r["openai_key"] == "ok" or r["groq_key"] == "ok"
    brain = "ready" if any(r[name] == "ok" for name in ("cloudflare", "sarvam_ai", "groq_key", "openai_key", "ollama")) else "unavailable"
    mic = "ready" if r["mic_configured"] == "ok" else "needs attention"
    wake = r.get("wake_engine", "unknown")
    timings = state.get("timings_ms", {})
    provider = state.get("last_provider") or "not measured yet"
    timing_text = ""
    if timings:
        total = timings.get("turn_dispatch") or timings.get("brain")
        if total is not None:
            timing_text = f" Last provider {provider}, {round(float(total))} milliseconds."
    return f"Health: microphone {mic}, wake {wake}, ears {'ready' if ears else 'unavailable'}, brain {brain}, state {state['state']}.{timing_text}"


def pro_summary() -> str:
    """Product-owner style readiness summary for voice or UI."""
    r = check()
    ready = []
    gaps = []

    if r.get("wake_reliable") == "ok":
        ready.append(f"wake engine {r.get('wake_engine')}")
    else:
        gaps.append("configure Porcupine or local wake model")

    if r.get("stt_engine") in {"deepgram", "openai", "groq"} and any(
        r.get(k) == "ok" for k in ("deepgram_key", "openai_key", "groq_key")
    ):
        ready.append(f"cloud ears {r.get('stt_engine')}")
    else:
        gaps.append("cloud speech recognition")

    if any(r.get(k) == "ok" for k in ("cloudflare", "sarvam_ai", "groq_key", "openai_key")):
        ready.append("cloud brain chain")
    elif r.get("ollama") == "ok":
        gaps.append("fast cloud brain")
    else:
        gaps.append("brain provider")

    if r.get("mic_configured") == "ok":
        ready.append("microphone")
    else:
        gaps.append("microphone")

    if r.get("google_token") == "ok":
        ready.append("Google")
    else:
        gaps.append("Google OAuth")

    if r.get("phone_adb") == "ok":
        ready.append("Android phone")
    else:
        gaps.append("Android phone connection")

    if not getattr(config, "BARGE_IN_ENABLED", False):
        gaps.append("validated acoustic echo cancellation for barge-in")

    ready_text = ", ".join(ready) if ready else "basic runtime"
    gap_text = ", ".join(gaps[:4]) if gaps else "no major gaps"
    return f"Pro status: ready: {ready_text}. Next gaps: {gap_text}."


def summary() -> str:
    r = check()
    lines = [f"{k:18s}: {v}" for k, v in r.items()]
    try:
        lines.append(f"{'mic_self_test':18s}: {mic_self_test()}")
    except Exception:
        pass
    return "Leha health:\n" + "\n".join(lines)


def main():
    import sys
    if "--probe-cloudflare" in sys.argv:
        data = cloudflare_probe()
        if "--json" in sys.argv:
            print(json.dumps(data, indent=2))
        else:
            print("Cloudflare probe:")
            for k, v in data.items():
                print(f"{k:14s}: {v}")
    elif "--json" in sys.argv:
        print(json.dumps(check(), indent=2))
    else:
        print(summary())


if __name__ == "__main__":
    main()
