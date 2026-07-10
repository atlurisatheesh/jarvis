"""Pro operations layer for Leha.

This module is intentionally read-mostly. It powers owner dashboards, voice
status commands, and product-readiness checks without starting extra TTS,
running destructive actions, or touching private credentials.
"""
from __future__ import annotations

from pathlib import Path
import json

from . import config
from .runtime_state import runtime


def _ok(value: bool) -> str:
    return "ok" if value else "missing"


def latency_status() -> dict:
    snap = runtime.snapshot()
    timings = snap.get("timings_ms", {}) or {}
    first_token = timings.get("brain_first_token")
    turn = timings.get("turn_dispatch") or timings.get("brain")
    stt = timings.get("stt")
    return {
        "state": snap.get("state"),
        "last_provider": snap.get("last_provider") or "not measured",
        "timings_ms": timings,
        "targets_ms": {
            "stt": 1000,
            "first_token": 1500,
            "turn_dispatch": 3000,
        },
        "ready": {
            "stt": stt is None or float(stt) <= 1000,
            "first_token": first_token is None or float(first_token) <= 1500,
            "turn_dispatch": turn is None or float(turn) <= 3000,
        },
    }


def voice_status() -> dict:
    engine = getattr(config, "TTS_ENGINE", "unknown")
    clone_ref = Path(getattr(config, "CLONE_TTS_REFERENCE", ""))
    return {
        "engine": engine,
        "live_voice": getattr(config, "EDGE_TTS_VOICE", ""),
        "clone_reference_present": clone_ref.is_file(),
        "clone_live_enabled": engine == "clone",
        "clone_note": (
            "GPU/hosted clone needed for live use"
            if engine != "clone"
            else "clone mode enabled; verify latency before daily use"
        ),
    }


def barge_in_status() -> dict:
    aec = bool(getattr(config, "AEC_ENABLED", False))
    barge = bool(getattr(config, "BARGE_IN_ENABLED", False))
    hardware = bool(getattr(config, "AEC_HARDWARE_DEVICE", None))
    speex_available = False
    try:
        import speexdsp  # noqa: F401
        speex_available = True
    except Exception:
        speex_available = False
    return {
        "enabled": barge,
        "aec_enabled": aec,
        "software_aec_available": speex_available,
        "hardware_aec_device": getattr(config, "AEC_HARDWARE_DEVICE", None) or "",
        "safe_to_enable": aec or hardware,
        "recommendation": (
            "Barge-in can be tested with current AEC settings."
            if (aec or hardware)
            else "Keep barge-in off until headset or acoustic echo cancellation is validated."
        ),
    }


def wake_data_status() -> dict:
    """Count wake-word training data and report whether it is enough to train."""
    positive_dirs = [
        config.BASE_DIR / "voices" / "wake_leha",
        config.BASE_DIR / "voices" / "wake_leha_retry",
        config.BASE_DIR / "voices" / "wake_leha_continuous",
        config.BASE_DIR / "voices" / "wake_leha_guided",
    ]
    positive_dirs.extend(sorted((config.BASE_DIR / "voices").glob("wake_leha_guided_*")))
    negative_dirs = [
        config.BASE_DIR.parent / "processed" / "guided_wake_negatives",
    ]
    negative_dirs.extend(sorted((config.BASE_DIR.parent / "processed").glob("wake_negative_guided_*")))
    positive_count = sum(len(list(p.glob("*.wav"))) for p in positive_dirs if p.is_dir())
    negative_count = sum(len(list(p.glob("*.wav"))) for p in negative_dirs if p.is_dir())
    good_positive_target = 150
    good_negative_target = 500
    return {
        "positive_clips": positive_count,
        "negative_clips": negative_count,
        "positive_target": good_positive_target,
        "negative_target": good_negative_target,
        "ready_for_training": positive_count >= good_positive_target and negative_count >= good_negative_target,
        "recommended_command": (
            "python tools/guided_wake_improvement.py --positives 120 --negatives 500 --train"
        ),
        "note": (
            "Collect more real Leha clips from this room."
            if positive_count < good_positive_target
            else "Positive data is enough; collect negatives or train/evaluate."
        ),
    }


def wake_validation_status() -> dict:
    from . import wake_openwakeword

    custom_models = wake_openwakeword._resolve_custom_models()
    model = Path(custom_models[0]) if custom_models else Path()
    report_path = config.BASE_DIR / "voices" / "leha_wake_manifest.json"
    report = {}
    if report_path.is_file():
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except Exception:
            report = {}
    data = wake_data_status()
    available = wake_openwakeword.is_available()
    hybrid = bool(getattr(config, "OWW_HYBRID_TRANSCRIPT_FALLBACK", False))
    return {
        "engine": "openwakeword+strict_transcript" if available and hybrid else (
            "openwakeword" if available else "strict_transcript"
        ),
        "available": available,
        "model_present": bool(custom_models),
        "model_path": str(model) if custom_models else "",
        "model_paths": custom_models,
        "threshold": float(getattr(config, "OWW_THRESHOLD", 0.0)),
        "required_hits": int(getattr(config, "OWW_REQUIRED_HITS", 2)),
        "hybrid_transcript_fallback": hybrid,
        "approved": bool(report.get("approved", False)),
        "eval_report": str(report_path),
        "eval_recall": report.get("held_out", {}).get("recall"),
        "eval_false_wake_rate": report.get("held_out", {}).get("false_wake_rate"),
        "validation_label": report.get("validation_label", "not measured"),
        "live_spot_check": report.get("live_spot_check", {}),
        "positive_sample_count": data["positive_clips"],
        "negative_sample_count": data["negative_clips"],
        "ready_for_training": data["ready_for_training"],
        "manual_protocol": [
            "Say Leha 20 times from normal distance.",
            "Play YouTube/music for 5 minutes and confirm no false wake.",
            "Say similar words like Layla, Lena, Leela and confirm no wake.",
            "Keep the two-hit threshold unless a new held-out evaluation improves recall without false wakes.",
        ],
    }


def wake_miss_status() -> dict:
    from . import wake_miss_log
    return wake_miss_log.status()


def android_hotword_status() -> dict:
    ppn = config.BASE_DIR.parent / "android-app" / "app" / "src" / "main" / "assets" / "leha_android.ppn"
    return {
        "porcupine_dependency": True,
        "custom_leha_ppn_present": ppn.is_file(),
        "custom_leha_ppn_path": str(ppn),
        "requires_picovoice_access_key_in_app": True,
        "fallback": (
            "built-in Jarvis when AccessKey exists but no custom .ppn; manual ARM LEHA when no AccessKey"
        ),
    }


def smart_home_status() -> dict:
    return {
        "configured": bool(getattr(config, "HOME_ASSISTANT_ENABLED", False)),
        "url_set": bool(getattr(config, "HOME_ASSISTANT_URL", "")),
        "token_set": bool(getattr(config, "HOME_ASSISTANT_TOKEN", "")),
        "hub": "Home Assistant",
        "note": (
            "Ready for entity/scene control."
            if getattr(config, "HOME_ASSISTANT_ENABLED", False)
            else "Set HOME_ASSISTANT_URL and .home_assistant_token to enable smart-home control."
        ),
    }


def streaming_status() -> dict:
    return {
        "brain_streaming_available": True,
        "listener_uses_streaming": True,
        "tts_sentence_streaming_available": True,
        "remaining_gap": "STT is still utterance-based; true streaming STT is the next latency upgrade.",
    }


def siri_parity_status() -> dict:
    """Concrete readiness map for Siri/Alexa/Jarvis-like behavior."""
    from . import health

    h = health.check()
    wake = wake_validation_status()
    barge = barge_in_status()
    stream = streaming_status()
    checks = {
        "wake_word": h.get("wake_reliable") == "ok",
        "echo_cancellation": bool(barge["safe_to_enable"]),
        "streaming_reply": bool(stream["brain_streaming_available"] and stream["tts_sentence_streaming_available"]),
        "safe_barge_in": bool(barge["enabled"] and barge["safe_to_enable"]),
        "mobile_hotword": bool(android_hotword_status()["custom_leha_ppn_present"]),
        "desktop_core": all(h.get(k) == "ok" for k in ("mic_configured", "deepgram_key")) and (
            h.get("cloudflare") == "ok" or h.get("groq_key") == "ok" or h.get("openai_key") == "ok"
        ),
    }
    next_steps = []
    if not checks["wake_word"]:
        next_steps.append("train and approve a local Leha wake model")
    if not checks["echo_cancellation"]:
        next_steps.append("use a headset/AEC mic or install validated software AEC")
    if not checks["safe_barge_in"]:
        next_steps.append("enable barge-in only after AEC is validated")
    if not checks["mobile_hotword"]:
        next_steps.append("add Android custom Leha hotword when available")
    return {
        "checks": checks,
        "wake": wake,
        "barge_in": barge,
        "streaming": stream,
        "ready": all(checks.values()),
        "next_steps": next_steps,
    }


def production_status() -> dict:
    root = config.BASE_DIR.parent
    required = [
        root / "scripts" / "install_production.ps1",
        root / "scripts" / "start_leha.ps1",
        root / "scripts" / "stop_leha.ps1",
        root / "scripts" / "restart_leha.ps1",
        root / "scripts" / "status_leha.ps1",
        root / "Start Leha Production.bat",
    ]
    return {
        "scripts_present": all(p.exists() for p in required),
        "missing_scripts": [str(p) for p in required if not p.exists()],
        "installer": str(root / "scripts" / "install_production.ps1"),
        "status_script": str(root / "scripts" / "status_leha.ps1"),
    }


def notification_policy() -> dict:
    quiet_start = getattr(config, "PROACTIVE_QUIET_HOURS_START", "")
    quiet_end = getattr(config, "PROACTIVE_QUIET_HOURS_END", "")
    return {
        "enabled": bool(getattr(config, "NOTIFIER_ENABLED", True)),
        "speak_background_jobs": bool(getattr(config, "PROACTIVE_SPEAK_BACKGROUND_JOBS", True)),
        "quiet_hours": {"start": quiet_start, "end": quiet_end},
        "max_spoken_per_hour": int(getattr(config, "PROACTIVE_MAX_SPOKEN_PER_HOUR", 8)),
        "speak_only_useful": bool(getattr(config, "PROACTIVE_SPEAK_ONLY_USEFUL", True)),
    }


def owner_settings() -> dict:
    from . import pro_settings
    data = pro_settings.load()
    data["requires_restart_to_apply_to_listener"] = True
    return data


def update_owner_settings(updates: dict) -> dict:
    from . import pro_settings
    data = pro_settings.save(updates)
    pro_settings.apply_to_config()
    data["requires_restart_to_apply_to_listener"] = True
    return data


def recent_logs(count: int = 80) -> list[str]:
    try:
        from . import log_manager
        return log_manager.read_recent(count=max(1, min(int(count), 300)))
    except Exception:
        return []


def audit_summary(limit: int = 10) -> dict:
    try:
        from .audit_log import get_audit_log
        entries = get_audit_log().read_recent(limit)
    except Exception:
        entries = []
    risky = []
    try:
        from . import skill_policy
        for entry in entries:
            tool = entry.get("tool", "")
            policy = skill_policy.get_policy(tool)
            if policy.risk_level in {"external", "destructive"}:
                risky.append(entry)
    except Exception:
        risky = []
    return {"recent": entries, "risky_recent": risky[-limit:]}


def dashboard_status() -> dict:
    from . import health

    h = health.check()
    gaps = []
    if h.get("wake_reliable") != "ok":
        gaps.append("wake reliability")
    if h.get("phone_adb") != "ok":
        gaps.append("Android phone connection")
    if not android_hotword_status()["custom_leha_ppn_present"]:
        gaps.append("Android custom Leha wake model")
    if not barge_in_status()["safe_to_enable"]:
        gaps.append("validated barge-in/AEC")
    if not voice_status()["clone_live_enabled"]:
        gaps.append("GPU/hosted cloned voice")
    if not smart_home_status()["configured"]:
        gaps.append("Home Assistant token/devices")

    return {
        "assistant": config.ASSISTANT_NAME,
        "build": getattr(config, "LEHA_BUILD", ""),
        "health": h,
        "runtime": runtime.snapshot(),
        "latency": latency_status(),
        "voice": voice_status(),
        "barge_in": barge_in_status(),
        "wake_validation": wake_validation_status(),
        "wake_misses": wake_miss_status(),
        "android_hotword": android_hotword_status(),
        "smart_home": smart_home_status(),
        "streaming": streaming_status(),
        "siri_parity": siri_parity_status(),
        "production": production_status(),
        "notifications": notification_policy(),
        "settings": owner_settings(),
        "audit": audit_summary(12),
        "logs": recent_logs(40),
        "gaps": gaps,
    }


def spoken_status() -> str:
    status = dashboard_status()
    h = status["health"]
    gaps = status["gaps"][:3]
    gap_text = ", ".join(gaps) if gaps else "no major gaps"
    return (
        f"Pro mode: wake {h.get('wake_engine')}, ears {h.get('stt_engine')}, "
        f"brain {'cloud ready' if h.get('cloudflare') == 'ok' else 'fallback ready'}. "
        f"Next gaps: {gap_text}."
    )


def spoken_siri_parity_status() -> str:
    status = siri_parity_status()
    if status["ready"]:
        return "Leha is ready for pro assistant mode, with wake, streaming, AEC, and barge-in."
    missing = ", ".join(status["next_steps"][:3])
    return f"Not fully Siri level yet. Next: {missing}."


def spoken_wake_data_status() -> str:
    data = wake_data_status()
    return (
        f"Wake data: {data['positive_clips']} positive and {data['negative_clips']} negative clips. "
        f"Target is {data['positive_target']} positive and {data['negative_target']} negative."
    )


def spoken_wake_miss_status() -> str:
    from .wake_miss_log import spoken_status as wake_miss_spoken_status
    return wake_miss_spoken_status()
