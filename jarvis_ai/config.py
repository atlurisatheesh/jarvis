"""Central configuration for Leha. Tweak values here, not in code."""
import os
import shutil
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
VOICES_DIR = BASE_DIR / "voices"
MEMORY_DIR = BASE_DIR / "memory_store"

# --- Logging (Phase 0) ---
# Logs live outside the package (D:\jarvis\logs) so the package dir stays clean.
LOG_DIR = str(BASE_DIR.parent / "logs")
LOG_FILE_NAME = os.environ.get("LEHA_LOG_FILE", "leha.log")
LOG_RETENTION_DAYS = int(os.environ.get("LOG_RETENTION_DAYS", "7"))
LOG_MAX_SIZE_MB = int(os.environ.get("LOG_MAX_SIZE_MB", "10"))
CRASH_ALERTS_ENABLED = os.environ.get("CRASH_ALERTS_ENABLED", "true").lower() == "true"

# --- Brain ---
# Engine: "groq" (cloud, instant), "local" (Ollama on CPU), "auto" (Groq → local fallback)
# "auto" = Groq cloud (smart, fast tool-calling) with local Ollama fallback on
# rate-limit/network error. Rate-limit raises -> silent local fallback (no double
# reply). Local qwen2.5:3b alone handles 80+ tools poorly, so prefer auto.
BRAIN_ENGINE = "auto"
GROQ_BRAIN_MODEL = "llama-3.3-70b-versatile"   # smarter + better tool-calling than 8b
# Only send these tools to the cloud brain (keeps each request small -> under
# the free-tier 6000 tokens/min limit). Reflexes in assistant_core handle the
# rest locally. Empty/None = send all (will hit rate limits).
GROQ_TOOL_ALLOWLIST = [
    # Device/media commands are handled locally before the brain. Keep cloud
    # schemas small so fast Groq requests do not exhaust the free quota.
    "calculate", "web_search", "get_weather", "current_location", "travel_distance", "set_reminder", "remember_fact",
    "read_screen", "see_screen", "search_file_contents", "find_anything",
    "ask_docs", "google_calendar_upcoming", "google_gmail_search",
    "google_drive_search", "google_contacts_search",
    # Google (Maps + OAuth read/write)
    "open_google_maps", "search_google_maps", "google_calendar_upcoming",
    "google_gmail_search", "google_drive_search", "google_contacts_search",
    "google_calendar_create", "google_gmail_send",
]
GROQ_TIMEOUT_SECONDS = 5
OPENAI_BRAIN_MODEL = os.environ.get("OPENAI_BRAIN_MODEL", "gpt-4.1-mini").strip()
OPENAI_BRAIN_TIMEOUT_SECONDS = 6

# --- Cloudflare Workers AI (primary cloud brain when configured) ---
# Store only a freshly created, least-privilege Workers AI token in
# D:\jarvis\.cloudflare_token. The account id can be supplied through the
# environment or the legacy .cloudflare_creds file. Neither file is committed.
def _parse_cloudflare_creds(raw: str) -> tuple[str, str]:
    """Parse local Cloudflare credentials without logging secrets.

    Accepted formats:
      account_id:api_token
      account_id=<id>\napi_token=<token>
      CLOUDFLARE_ACCOUNT_ID=<id>\nCLOUDFLARE_API_TOKEN=<token>

    Older setup notes used a single colon-separated line. Newer notes often
    paste labelled values, so keep both forms working.
    """
    raw = (raw or "").strip()
    if not raw:
        return "", ""

    if "\n" not in raw and raw.count(":") == 1:
        a, _, t = raw.partition(":")
        return a.strip(), t.strip()

    values: dict[str, str] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, _, v = line.partition("=")
        elif ":" in line:
            k, _, v = line.partition(":")
        else:
            continue
        key = k.strip().lower().replace(" ", "_").replace("-", "_")
        values[key] = v.strip().strip('"').strip("'")

    account = (
        values.get("cloudflare_account_id")
        or values.get("account_id")
        or values.get("account")
        or values.get("accountid")
    )
    token = (
        values.get("cloudflare_api_token")
        or values.get("api_token")
        or values.get("apikey")
        or values.get("api_key")
        or values.get("token")
    )
    return account or "", token or ""


def _load_cloudflare():
    acct = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
    tok = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
    if acct and tok:
        return acct, tok

    token_file = BASE_DIR.parent / ".cloudflare_token"
    if acct and token_file.exists():
        return acct, token_file.read_text(encoding="utf-8").strip()

    f = BASE_DIR.parent / ".cloudflare_creds"
    if f.exists():
        raw = f.read_text(encoding="utf-8").strip()
        acct, tok = _parse_cloudflare_creds(raw)
        if acct and tok:
            return acct, tok
    return "", ""


CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_API_TOKEN = _load_cloudflare()
# "auto" enables Cloudflare only when both account id and token are present.
# Set CF_BRAIN_ENABLED=0 to force-disable, or 1 to force-enable.
_CF_ENABLED_RAW = os.environ.get("CF_BRAIN_ENABLED", "auto").strip().lower()
CF_BRAIN_ENABLED = (
    _CF_ENABLED_RAW in {"1", "true", "yes", "on"}
    or (
        _CF_ENABLED_RAW in {"", "auto"}
        and bool(CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN)
    )
)
CF_BRAIN_MODEL = os.environ.get(
    "CF_BRAIN_MODEL", "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
).strip()
# Avoid making the voice loop wait behind a cold or overloaded remote model.
CF_BRAIN_TIMEOUT_SECONDS = int(os.environ.get("CF_BRAIN_TIMEOUT_SECONDS", "3"))
# Do not block the always-on microphone while retrying a throttled cloud model.
# A short spoken status is better than a frozen assistant.
GROQ_RATE_LIMIT_RETRY_SECONDS = 0
GROQ_RATE_LIMIT_REPLY = "My fast brain is busy for a moment, Sir. Please try again."
# Skip a cloud provider briefly after it fails or rate-limits instead of making
# every new spoken command wait for the same known-bad request.
PROVIDER_COOLDOWN_SECONDS = int(os.environ.get("PROVIDER_COOLDOWN_SECONDS", "180"))

# --- NVIDIA API / GLM brain ---
# NVIDIA NIM/OpenAI-compatible endpoint. Store the key in D:\jarvis\.nvidia_key
# or env NVIDIA_API_KEY. Default model matches the NVIDIA Integrate snippet.
# Key from env or local gitignored file (.nvidia_key).
def _load_nvidia_key() -> str:
    key = os.environ.get("NVIDIA_API_KEY", "").strip()
    if key:
        return key
    path = BASE_DIR.parent / ".nvidia_key"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    return ""


NVIDIA_API_KEY = _load_nvidia_key()
NVIDIA_BASE_URL = os.environ.get("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1").strip()
NVIDIA_BRAIN_MODEL = os.environ.get("NVIDIA_BRAIN_MODEL", "z-ai/glm-5.2").strip()
NVIDIA_INDIAN_LANGUAGE_MODEL = os.environ.get("NVIDIA_INDIAN_LANGUAGE_MODEL", "sarvamai/sarvam-m").strip()
NVIDIA_BRAIN_TIMEOUT_SECONDS = int(os.environ.get("NVIDIA_BRAIN_TIMEOUT_SECONDS", "3"))
# Put NVIDIA first when enabled. Set NVIDIA_BRAIN_PRIORITY=0 to place it after
# Cloudflare in the fallback chain.
NVIDIA_BRAIN_PRIORITY = os.environ.get("NVIDIA_BRAIN_PRIORITY", "1").lower() in {"1", "true", "yes", "on"}
# NVIDIA has been timing out for normal English turns. Keep it as the first
# Indian-language Sarvam route, but avoid making every English question wait on
# it unless explicitly requested.
NVIDIA_BRAIN_ENGLISH_ENABLED = os.environ.get("NVIDIA_BRAIN_ENGLISH_ENABLED", "false").lower() in {"1", "true", "yes", "on"}
# Auto-enable when key is present. Set NVIDIA_BRAIN_ENABLED=0 to force-disable.
_NV_ENABLED_RAW = os.environ.get("NVIDIA_BRAIN_ENABLED", "auto").strip().lower()
NVIDIA_BRAIN_ENABLED = (
    _NV_ENABLED_RAW in {"1", "true", "yes", "on"}
    or (_NV_ENABLED_RAW in {"", "auto"} and bool(NVIDIA_API_KEY))
)

# Sarvam AI direct API fallback for Indian-language turns. NVIDIA Sarvam stays
# first priority; this is used only if NVIDIA fails/rate-limits.
SARVAM_API_KEY = (
    os.environ.get("SARVAM_API_KEY", "").strip().replace("\ufeff", "")
    or ((BASE_DIR.parent / ".sarvam_key").read_text(encoding="utf-8-sig").strip().replace("\ufeff", "")
        if (BASE_DIR.parent / ".sarvam_key").exists() else "")
)
SARVAM_BASE_URL = os.environ.get("SARVAM_BASE_URL", "https://api.sarvam.ai/v1").strip()
SARVAM_CHAT_MODEL = os.environ.get("SARVAM_CHAT_MODEL", "sarvam-30b").strip()
SARVAM_TIMEOUT_SECONDS = int(os.environ.get("SARVAM_TIMEOUT_SECONDS", "4"))
# Sarvam speech-to-text (saarika) — Indian-language specialist ears. Used as a
# rescue provider when Deepgram transcribes Indian speech with low confidence
# (nova-3 does not support Telugu/Tamil/Kannada well), and as a fallback tier.
SARVAM_STT_URL = os.environ.get("SARVAM_STT_URL", "https://api.sarvam.ai/speech-to-text").strip()
SARVAM_STT_MODEL = os.environ.get("SARVAM_STT_MODEL", "saarika:v2.5").strip()
# Below this Deepgram word confidence, the clip is re-transcribed with Sarvam
# saarika (auto Indian language detection) and the better result is used.
STT_DEEPGRAM_MIN_CONFIDENCE = float(os.environ.get("STT_DEEPGRAM_MIN_CONFIDENCE", "0.60"))
_SARVAM_ENABLED_RAW = os.environ.get("SARVAM_AI_ENABLED", "auto").strip().lower()
SARVAM_AI_ENABLED = (
    _SARVAM_ENABLED_RAW in {"1", "true", "yes", "on"}
    or (_SARVAM_ENABLED_RAW in {"", "auto"} and bool(SARVAM_API_KEY))
)

# Circuit breaker thresholds (Phase 2).  A provider is opened after this many
# consecutive failures; it stays open for PROVIDER_COOLDOWN_SECONDS, then
# enters half-open for CB_HALF_OPEN_SECONDS before a probe is allowed.
CB_FAILURE_THRESHOLD = int(os.environ.get("CB_FAILURE_THRESHOLD", "1"))
CB_HALF_OPEN_SECONDS = int(os.environ.get("CB_HALF_OPEN_SECONDS", "30"))

# Skill result cache (Phase 2).  Disabled by default; enable to cache read-only
# skill outputs (weather, system_info, calendar, ...) with a per-skill TTL.
SKILL_CACHE_ENABLED = os.environ.get("SKILL_CACHE_ENABLED", "true").lower() == "true"
SKILL_CACHE_MAX_SIZE = int(os.environ.get("SKILL_CACHE_MAX_SIZE", "128"))

# Background job queue (Phase 2).  Long-running actions run in the background.
BACKGROUND_JOBS_ENABLED = os.environ.get("BACKGROUND_JOBS_ENABLED", "true").lower() == "true"
BACKGROUND_JOBS_WORKERS = int(os.environ.get("BACKGROUND_JOBS_WORKERS", "2"))

# Proactive notifier (Phase D). Background jobs/reminders can announce through
# the one central speech queue instead of creating a second voice.
NOTIFIER_ENABLED = os.environ.get("NOTIFIER_ENABLED", "true").lower() == "true"
NOTIFIER_MAX_QUEUE = int(os.environ.get("NOTIFIER_MAX_QUEUE", "50"))
PROACTIVE_SPEAK_BACKGROUND_JOBS = os.environ.get("PROACTIVE_SPEAK_BACKGROUND_JOBS", "true").lower() == "true"
PROACTIVE_SPEAK_ONLY_USEFUL = os.environ.get("PROACTIVE_SPEAK_ONLY_USEFUL", "true").lower() == "true"
PROACTIVE_MAX_SPOKEN_PER_HOUR = int(os.environ.get("PROACTIVE_MAX_SPOKEN_PER_HOUR", "8"))
PROACTIVE_QUIET_HOURS_START = os.environ.get("PROACTIVE_QUIET_HOURS_START", "22:30").strip()
PROACTIVE_QUIET_HOURS_END = os.environ.get("PROACTIVE_QUIET_HOURS_END", "07:00").strip()

# Acoustic echo cancellation (Phase 3).  Software AEC enables barge-in with
# laptop speakers; hardware headsets do AEC in the device itself.
AEC_ENABLED = os.environ.get("AEC_ENABLED", "false").lower() == "true"
AEC_LIBRARY = os.environ.get("AEC_LIBRARY", "speexdsp").strip()
AEC_HARDWARE_DEVICE = os.environ.get("AEC_HARDWARE_DEVICE", "").strip() or None

# Speech manager (Phase 3).  Central queue guarantees one voice output at a time.
SPEECH_MANAGER_ENABLED = os.environ.get("SPEECH_MANAGER_ENABLED", "true").lower() == "true"
SPEECH_STALE_SECONDS = float(os.environ.get("SPEECH_STALE_SECONDS", "35"))
# Brain tokens are consumed while previous TTS chunks play. This is true
# pipelining: generation does not pause for audio, and only one worker speaks.
TTS_STREAM_FIRST_WORDS = int(os.environ.get("TTS_STREAM_FIRST_WORDS", "5"))
TTS_STREAM_MAX_WORDS = int(os.environ.get("TTS_STREAM_MAX_WORDS", "16"))
TTS_STREAM_QUEUE_MAX = int(os.environ.get("TTS_STREAM_QUEUE_MAX", "4"))
TTS_STREAM_DRAIN_SECONDS = float(os.environ.get("TTS_STREAM_DRAIN_SECONDS", "90"))

# Audit log (Phase 4).  Records every tool execution to memory_store/audit.logl.
AUDIT_LOG_ENABLED = os.environ.get("AUDIT_LOG_ENABLED", "true").lower() == "true"
AUDIT_LOG_MAX_SIZE_MB = int(os.environ.get("AUDIT_LOG_MAX_SIZE_MB", "50"))

# Undo stack (Phase 4).  Reversible actions can be undone via "Leha undo".
UNDO_ENABLED = os.environ.get("UNDO_ENABLED", "true").lower() == "true"
UNDO_STACK_DEPTH = int(os.environ.get("UNDO_STACK_DEPTH", "20"))

# Google services (Phase 5).  Rate limiting and confirmation requirements.
GOOGLE_RATE_LIMIT_PER_MINUTE = int(os.environ.get("GOOGLE_RATE_LIMIT_PER_MINUTE", "30"))
GOOGLE_CONFIRM_REQUIRED = {"create", "send", "delete"}

OLLAMA_HOST = "http://127.0.0.1:11434"
# Local brain model (used when BRAIN_ENGINE="local" or as auto fallback).
BRAIN_MODEL = "qwen2.5:3b"
# Cap reply length -> faster finish + shorter spoken answers.
# Indian languages (Telugu, Hindi, etc.) use more tokens per word than English,
# so keep this at 200 minimum to avoid mid-word truncation.
BRAIN_NUM_PREDICT = 200
# Keep the model loaded in RAM so it doesn't reload (adds latency) between turns.
BRAIN_KEEP_ALIVE = "30m"
ASSISTANT_NAME = "Leha"
USER_NAME = "Sir"
ASSISTANT_MODE = "ultra"
LEHA_BUILD = "2026.07.10-hybrid-streaming"


def _load_version() -> str:
    """Read the semantic version from the VERSION file next to this package."""
    try:
        return (BASE_DIR / "VERSION").read_text(encoding="utf-8").strip() or "0.0.0"
    except Exception:
        return "0.0.0"


# Semantic version (Phase 9). LEHA_BUILD stays as the human build tag.
LEHA_VERSION = _load_version()

# --- Device manager (Phase 6) ---
# Pairing approval, session expiry, per-device rate limits and capability
# scoping for remote clients. Disabled by default so the existing PIN-gated
# web/Android path is unchanged until the owner opts in.
DEVICE_MANAGER_ENABLED = os.environ.get("DEVICE_MANAGER_ENABLED", "false").lower() == "true"
DEVICE_SESSION_TTL_SECONDS = int(os.environ.get("DEVICE_SESSION_TTL_SECONDS", "3600"))
DEVICE_RATE_LIMIT_PER_MINUTE = int(os.environ.get("DEVICE_RATE_LIMIT_PER_MINUTE", "60"))

# --- Structured memory (Phase 8) ---
STRUCTURED_MEMORY_ENABLED = os.environ.get("STRUCTURED_MEMORY_ENABLED", "true").lower() == "true"

# --- Persistent/semantic conversation memory (Phases B/C) ---
# Recent turns are stored as JSON and rehydrated into new brains after restart.
# Semantic memory uses the existing ChromaDB/RAG stack in the background so
# normal spoken replies do not wait on embeddings.
CONVERSATION_PERSIST_ENABLED = os.environ.get("CONVERSATION_PERSIST_ENABLED", "true").lower() == "true"
CONVERSATION_PERSIST_TURNS = int(os.environ.get("CONVERSATION_PERSIST_TURNS", "50"))
SEMANTIC_MEMORY_ENABLED = os.environ.get("SEMANTIC_MEMORY_ENABLED", "true").lower() == "true"
SEMANTIC_MEMORY_INJECT_ENABLED = os.environ.get("SEMANTIC_MEMORY_INJECT_ENABLED", "false").lower() == "true"
SEMANTIC_MEMORY_RESULTS = int(os.environ.get("SEMANTIC_MEMORY_RESULTS", "3"))

# --- Startup health gate (Phase E) ---
STARTUP_HEALTH_GATE_ENABLED = os.environ.get("STARTUP_HEALTH_GATE_ENABLED", "true").lower() == "true"
STARTUP_HEALTH_REQUIRED = {"mic", "ears", "brain"}
MIC_SELF_TEST_SECONDS = float(os.environ.get("MIC_SELF_TEST_SECONDS", "0.25"))

# Home Assistant knobs (Phase 7) are defined lower down, after _load_secret.
# The wake acknowledgement is pre-rendered in the active ElevenLabs clone, so
# neural wake can answer immediately without a cloud TTS round trip.
SPEAK_WAKE_ACK = True

SYSTEM_PROMPT = (
    "You are Leha, a capable voice assistant on the user's Windows laptop. "
    f"Address the user as {USER_NAME}. You are general-purpose: answer ANY question or "
    "request from your own knowledge (facts, advice, writing, translation, coding, math, "
    "explanations) without needing a tool. Only call a tool when the user wants a real "
    "action performed (control the PC/phone, files, web, reminders, crop diagnosis, etc.). "
    "For music/video requests like 'play music on YouTube' or 'play Ilayaraja Telugu songs', "
    "use play_youtube with the requested song, artist, language, or genre; do not just open "
    "YouTube or search Google. "
    "For Windows system control: sleep_pc/restart_pc/shutdown_pc for power; kill_process to "
    "close stubborn apps; set_brightness for screen; toggle_wifi for network; dark_mode for "
    "theme; snap_window to arrange windows; show_desktop/minimize_all for desktop. "
    "For anything no specific tool covers, you can use run_command. "
    "When the user refers to 'this', 'the screen', or what they are looking at, call "
    "see_screen (vision) or read_screen (OCR) to look before answering. "
    "To find the user's own files/notes/info, use find_anything or search_file_contents; "
    "for recently changed files use recent_files. "
    "For email questions ('any new mail', 'find the email from X', 'hotel confirmation'), "
    "use unread_email, recent_email, or search_email with Gmail search syntax. "
    "For phone messages use phone_read_sms / phone_unread_sms; to text someone use "
    "phone_send_sms or phone_whatsapp; to call use phone_call. "
    "For calendar use google_calendar_upcoming to read, google_calendar_create to add. "
    "You have broad local access to the user's laptop tools, files, apps, browser, screen, "
    "clipboard, Google account, and connected phone where configured. "
    "For destructive, external, or disruptive actions such as shutdown, restart, sleep, "
    "kill process, Wi-Fi changes, sending messages/email, or calls, ask for confirmation "
    "and do not execute until the user says yes. "
    "To send email, call google_gmail_send WITHOUT confirm first, read the preview "
    "back to the user, and only call again with confirm=true after they say yes. "
    "ALWAYS use the calculate tool for any arithmetic instead of doing it in your head. "
    "To check or change something on the computer (disk, processes, files, settings), call "
    "run_command instead of asking the user to provide it. "
    "Answer in ONE short sentence, max ~15 words, no markdown. Give the answer directly -- "
    "Understand and reply in Indian languages including Hindi, Telugu, Tamil, Kannada, "
    "Malayalam, Marathi, Gujarati, Bengali, and Hinglish. Reply in the same language "
    "or mixed style the user used unless they ask for another language. "
    "Never expose reasoning or narration like 'the user asked', 'let me recall', "
    "'I know that', or translation explanation; just answer. "
    "NO filler, NO 'if you need anything else', NO restating the question. "
    "Never invent tool output. If truly ambiguous, ask one short question."
)

# --- Ears (speech-to-text) ---
# "auto" prefers Deepgram, then OpenAI, then Groq, then local Whisper based
# on available keys. Deepgram is the active low-latency ears provider.
STT_ENGINE = os.environ.get("STT_ENGINE", "auto").strip().lower()
# Key from env, or a local gitignored file (.groq_key) next to the project.
def _load_groq_key():
    k = os.environ.get("GROQ_API_KEY", "").strip()
    if k:
        return k
    f = BASE_DIR.parent / ".groq_key"
    if f.exists():
        return f.read_text(encoding="utf-8").strip()
    return ""
GROQ_API_KEY = _load_groq_key()
GROQ_STT_MODEL = "whisper-large-v3"


def _load_secret(name: str, filename: str = "") -> str:
    value = os.environ.get(name, "").strip()
    if value:
        return value
    if filename:
        path = BASE_DIR.parent / filename
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
    return ""

WHISPER_MODEL = "small"       # used when STT_ENGINE="local"
WHISPER_DEVICE = "cpu"
WHISPER_COMPUTE = "int8"
WHISPER_LANG = os.environ.get("WHISPER_LANG", "").strip() or None

# Optional cloud speech-to-text providers. Keep keys in environment variables
# or local ignored files next to the project: .deepgram_key / .openai_key.
DEEPGRAM_API_KEY = _load_secret("DEEPGRAM_API_KEY", ".deepgram_key")
DEEPGRAM_STT_MODEL = os.environ.get("DEEPGRAM_STT_MODEL", "nova-3").strip()
DEEPGRAM_WAKE_RETRY_ENABLED = os.environ.get("DEEPGRAM_WAKE_RETRY_ENABLED", "true").lower() == "true"
DEEPGRAM_WAKE_KEYWORDS = os.environ.get(
    "DEEPGRAM_WAKE_KEYWORDS", "Leha:5,leha:5,Leah:4,Leeha:4"
).strip()
# Prefer the verified local key file. A stale inherited Windows environment
# variable previously overrode it and caused OpenAI fallback 401 errors.
OPENAI_API_KEY = _load_secret("", ".openai_key") or os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_STT_MODEL = os.environ.get("OPENAI_STT_MODEL", "gpt-4o-mini-transcribe").strip()
STT_REQUEST_TIMEOUT_SECONDS = 3
STT_WAKE_REQUEST_TIMEOUT_SECONDS = float(
    os.environ.get("STT_WAKE_REQUEST_TIMEOUT_SECONDS", "2.2")
)
SAVE_LAST_COMMAND_AUDIO = os.environ.get(
    "SAVE_LAST_COMMAND_AUDIO", "true"
).lower() in {"1", "true", "yes", "on"}
LAST_COMMAND_AUDIO_PATH = str(BASE_DIR.parent / "logs" / "last_command.wav")
# Keep an always-on assistant responsive. Set True only when local Whisper is
# already warm and you explicitly prefer a slow offline fallback.
STT_CLOUD_FALLBACK_TO_LOCAL = False

# --- Home Assistant (Phase 7) ---
# Scoped long-lived access token + base URL. Empty token => "not configured"
# graceful degrade; nothing is contacted until both are set.
HOME_ASSISTANT_URL = os.environ.get("HOME_ASSISTANT_URL", "").strip()
HOME_ASSISTANT_TOKEN = _load_secret("HOME_ASSISTANT_TOKEN", ".home_assistant_token")
HOME_ASSISTANT_ENABLED = bool(HOME_ASSISTANT_URL and HOME_ASSISTANT_TOKEN)

# --- Wake word / audio ---
SAMPLE_RATE = 16000

# --- Porcupine wake word (highly recommended — replaces Whisper-substring) ---
# Get free access key at: https://console.picovoice.ai/
# Then pip install pvporcupine
PORCUPINE_ACCESS_KEY = os.environ.get("PORCUPINE_ACCESS_KEY", "").strip()
# Optional: path to custom "Leha" .ppn keyword file from console.picovoice.ai
# Without it, falls back to built-in "jarvis" keyword (say "Jarvis" to wake)
PORCUPINE_KEYWORD_PATH = os.environ.get("PORCUPINE_KEYWORD_PATH", "").strip()

# openwakeword (offline, no signup, no API key — runs entirely locally)
# Pre-trained "hey_jarvis" model downloads on first run (~30MB).
# Falls back to Whisper substring matching if OWW_ENABLED is False.
# Priority: Porcupine > openWakeWord > local ONNX > Whisper fallback.
OWW_ENABLED = True
# Custom trained "Leha" models (from kaggle_wake_job/train_leha_oww.ipynb).
# All listed models load simultaneously — either phrase wakes Leha.
# Files are missing until you train them; missing entries are skipped safely.
# NOTE (2026-07-03): OWW disabled until a real trained `leha.onnx` openwakeword
# model is produced. The configured custom files (leha.onnx / hey_leha.onnx) do
# not exist on disk, so OWW fell back to the built-in "hey jarvis" wake word —
# Leha would only respond to "hey jarvis", NOT "leha". With OWW off, the
# listener uses the fuzzy transcript wake (Deepgram STT + wake_phrases) which
# recognises "Leha" and its common STT manglings. Long-term fix: train a Leha
# openwakeword model via kaggle_wake_job/train_leha_oww.ipynb and drop it at
# voices/leha.onnx, then set OWW_ENABLED = True again.
OWW_CUSTOM_MODELS = [
    "voices/leha.onnx",       # single-word wake: "leha"
    "voices/hey_leha.onnx",   # two-word wake: "hey leha"
]
OWW_MODEL_NAME = "hey_jarvis"  # built-in fallback when no custom models present
OWW_MODEL_PATH = os.environ.get("OWW_MODEL_PATH", "").strip()  # legacy single path
OWW_THRESHOLD = 0.3   # 0.3=sensitive, 0.7=strict — fresh synthetic-trained Leha models score real voices lower; raise later if false wakes appear
# One-hit evaluation reached only 7.7% recall and introduced 1.0% false wakes,
# so two neural hits remain mandatory. The strict wake-biased STT rescue is the
# reliable recovery path when this weak neural candidate misses a short call.
OWW_REQUIRED_HITS = int(os.environ.get("OWW_REQUIRED_HITS", "2"))
# The owner-adapted model is a fast first-stage detector. If it misses an
# utterance, capture that utterance and run the existing strict transcript
# wake gate so recall never depends on the neural model alone.
OWW_HYBRID_TRANSCRIPT_FALLBACK = os.environ.get(
    "OWW_HYBRID_TRANSCRIPT_FALLBACK", "true"
).lower() == "true"
# Ignore faint TV/speaker chatter before spending time on cloud wake STT. This
# applies only while idle; command capture after wake keeps the calibrated gate.
OWW_IDLE_VAD_START_RMS = float(os.environ.get("OWW_IDLE_VAD_START_RMS", "140"))

# Locally trained Leha wake model. This lightweight ONNX detector is trained
# from the user's private wake clips and runs before cloud transcription.
CUSTOM_WAKE_MODEL_PATH = os.environ.get(
    "CUSTOM_WAKE_MODEL_PATH", str(BASE_DIR / "voices" / "leha_wake_model.onnx")
).strip()


def _env_bool_auto(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "auto").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


# Auto-enable the private wake model when the trained ONNX file exists. This
# makes Leha use a real wake detector before falling back to transcript fuzz.
CUSTOM_WAKE_ENABLED = _env_bool_auto(
    "CUSTOM_WAKE_ENABLED",
    Path(CUSTOM_WAKE_MODEL_PATH).is_file(),
)
# The first live test saw speaker/room false positives near 0.951. Recorded
# Leha samples score near 1.0, so use a conservative production threshold.
CUSTOM_WAKE_THRESHOLD = 0.995
CUSTOM_WAKE_REQUIRE_APPROVAL = os.environ.get("CUSTOM_WAKE_REQUIRE_APPROVAL", "true").lower() == "true"
CUSTOM_WAKE_FORCE_UNAPPROVED = False
CUSTOM_WAKE_EVAL_REPORT = os.environ.get(
    "CUSTOM_WAKE_EVAL_REPORT", str(BASE_DIR.parent / "processed" / "wake_eval_report.json")
).strip()

# Wake word additional settings
WAKE_COOLDOWN_SECONDS = int(os.environ.get("WAKE_COOLDOWN_SECONDS", "4"))  # seconds after wake to ignore re-trigger
WAKE_CONFIDENCE_LOG = os.environ.get("WAKE_CONFIDENCE_LOG", "").strip()  # file path for wake confidence log
WAKE_MISS_LOG = os.environ.get(
    "WAKE_MISS_LOG", str(BASE_DIR.parent / "logs" / "wake_misses.jsonl")
).strip()
WAKE_DASHBOARD_ENABLED = os.environ.get("WAKE_DASHBOARD_ENABLED", "false").lower() == "true"  # system tray dashboard
# Free local fallback: when no approved neural wake model is active, keep the
# transcript wake matcher strict. This reduces false wakes from room audio such
# as "yeah", "layer", "later", or music lyrics being mangled as Leha.
TRANSCRIPT_WAKE_STRICT = os.environ.get("TRANSCRIPT_WAKE_STRICT", "true").lower() != "false"

# Mic selection + gain. The Windows DEFAULT mic captured silence on this laptop;
# device 13 ("Microphone Array 4") was the only live one in the scan. Set the
# index here (run diag_mic_scan.py to re-check; indices can change on reboot).
MIC_DEVICE = 12               # Microphone Array 3: supports the always-on callback stream
INPUT_GAIN = 2.0              # mild boost; headset speech rms ~300

# --- Command capture ---
COMMAND_SECONDS = 5           # how long to listen after wake

# --- Mouth (text-to-speech) ---
# "edge" is the live/instant human voice.
# "hf" calls a warm Hugging Face Inference Endpoint.
# Clone mode is disabled for live use: CPU synthesis takes around a minute and
# can leave delayed replies. Keep the reference setup below for a later GPU run.
# Use the neural female voice for live replies. Windows SAPI remains available
# only as a diagnostic fallback when the neural service itself is unavailable.
# --- ElevenLabs cloned voice (paid, ~0.3s latency, speaks Indian languages) ---
ELEVENLABS_API_KEY = _load_secret("ELEVENLABS_API_KEY", ".elevenlabs_key")
# Voice id of the owner's cloned voice. Created once via
# tools/setup_elevenlabs_voice.py and stored in .elevenlabs_voice (gitignored).
ELEVENLABS_VOICE_ID = _load_secret("ELEVENLABS_VOICE_ID", ".elevenlabs_voice")
# multilingual v2 renders voice clones much more faithfully than flash;
# ~1s latency instead of ~0.3s, worth it for realism. Set ELEVENLABS_MODEL
# env to eleven_flash_v2_5 to trade realism for speed/cheaper credits.
ELEVENLABS_MODEL = os.environ.get("ELEVENLABS_MODEL", "eleven_multilingual_v2").strip()
ELEVENLABS_TIMEOUT_SECONDS = int(os.environ.get("ELEVENLABS_TIMEOUT_SECONDS", "10"))
ELEVENLABS_STABILITY = float(os.environ.get("ELEVENLABS_STABILITY", "0.50"))
ELEVENLABS_SIMILARITY_BOOST = float(os.environ.get("ELEVENLABS_SIMILARITY_BOOST", "0.90"))
ELEVENLABS_STYLE = float(os.environ.get("ELEVENLABS_STYLE", "0.15"))
ELEVENLABS_SPEAKER_BOOST = os.environ.get(
    "ELEVENLABS_SPEAKER_BOOST", "true"
).lower() in {"1", "true", "yes", "on"}
ELEVENLABS_OUTPUT_GAIN = float(os.environ.get("ELEVENLABS_OUTPUT_GAIN", "2.0"))
ELEVENLABS_PHRASE_CACHE_DIR = str(VOICES_DIR / "elevenlabs_cache")
ELEVENLABS_CACHE_PHRASES = {"yes sir", "ready sir", "leha online"}

# Default voice engine: the cloned ElevenLabs voice when key+voice exist,
# otherwise the free Edge neural voice. Edge always remains the fallback.
_TTS_DEFAULT = "elevenlabs" if (ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID) else "edge"
TTS_ENGINE = os.environ.get("TTS_ENGINE", _TTS_DEFAULT).strip().lower() or _TTS_DEFAULT
TTS_RATE = 175
# Neerja is a female Indian-English neural voice. It is not a true clone, but
# it is much more natural for live assistant replies than the older system voice.
EDGE_TTS_VOICE = "en-IN-NeerjaNeural"
EDGE_TTS_RATE = "-3%"
EDGE_TTS_PITCH = "+0Hz"
# Edge TTS needs internet access. If it is temporarily unavailable, do not let
# Windows pick its default (often male) narrator as the audible fallback.
POWERSHELL_TTS_VOICE = "Microsoft Zira Desktop"
VOICE_REFERENCE_AUDIO = [
    str(BASE_DIR.parent / "WhatsApp%20Video%202026-02-20%20at%208.26.37%20PM_audio_cleaned.mp3"),
    str(BASE_DIR.parent / "WhatsApp%20Video%202026-02-13%20at%208.59.02%20PM_audio_cleaned.mp3"),
]
CLONE_TTS_REFERENCE = str(VOICES_DIR / "leha_reference_mix.wav")
CLONE_TTS_MODEL_DIR = str(VOICES_DIR / "hf_cache" / "chatterbox")
CLONE_TTS_DEVICE = "cpu"      # set "cuda" only on a machine with NVIDIA CUDA
CLONE_TTS_TIMEOUT_SECONDS = 180
# When clone synthesis fails or times out, fall back to the fast Edge neural
# voice instead of staying silent. A silent assistant reads as broken.
CLONE_TTS_STRICT = os.environ.get("CLONE_TTS_STRICT", "false").lower() == "true"
# Owner-voice phrase cache: short fixed phrases (wake acks, greetings) that
# were pre-rendered in the cloned voice play instantly from disk, while long
# dynamic answers use the fast Edge neural voice.
# DEFAULT OFF (2026-07-10): mixing the cloned voice for some phrases with the
# Edge voice for everything else sounded like "two different assistants", and
# the cached clips still carry reference-audio noise. Re-enable after the
# cache is denoised/re-rendered, or when all speech can use the cloned voice.
CLONE_PHRASE_CACHE_DIR = str(VOICES_DIR / "clone_cache")
CLONE_PHRASE_CACHE_ENABLED = os.environ.get("CLONE_PHRASE_CACHE_ENABLED", "false").lower() == "true"
CLONE_TTS_EXAGGERATION = 0.5
CLONE_TTS_CFG_WEIGHT = 0.5
CLONE_TTS_TEMPERATURE = 0.8
PIPER_VOICE = str(VOICES_DIR / "en_US-lessac-medium.onnx")

# Hugging Face cloud TTS. For instant replies, use a dedicated always-warm
# Inference Endpoint URL, not serverless/cold-start inference.
HF_TOKEN = _load_secret("HF_TOKEN", ".hf_token")
HF_TTS_ENDPOINT_URL = os.environ.get("HF_TTS_ENDPOINT_URL", "").strip()
HF_TTS_MODEL = os.environ.get("HF_TTS_MODEL", "").strip()
HF_TTS_TIMEOUT_SECONDS = 12
HF_TTS_FALLBACK_TO_EDGE = True
# Output device for sounddevice TTS playback. None = OS default (same as PowerShell MediaPlayer).
# Run: python -c "import sounddevice as sd; print(sd.query_devices())" to list devices.
# Windows exposes two active Senary speaker endpoints on this laptop. The
# system default (index 3) completes playback but is inaudible; index 4 is the
# physical "Speakers (2- Senary Audio)" route verified during diagnostics.
OUTPUT_DEVICE = int(os.environ.get("LEHA_OUTPUT_DEVICE", "4"))

# --- Telegram bridge (Phase 4) — talk to Leha from your phone, anywhere ---
# Get a token from @BotFather (/newbot), then either set env JARVIS_TG_TOKEN
# or save the token to D:\jarvis\.tg_token (gitignored, same as .groq_key).
TELEGRAM_TOKEN = _load_secret("JARVIS_TG_TOKEN", ".tg_token")
# Your numeric Telegram user id(s) from @userinfobot. Empty list = allow anyone
# (NOT recommended — anyone who finds the bot could control your laptop).
TELEGRAM_ALLOWED_USERS = []

# --- Web app (PWA) access PIN ---
# Phone must enter this PIN once to use the web app. Auto-generated 6-digit on
# first run, saved to .web_pin (gitignored). Override via env LEHA_WEB_PIN.
def _load_or_make_pin() -> str:
    p = _load_secret("LEHA_WEB_PIN", ".web_pin")
    if p:
        return p
    import secrets
    pin = f"{secrets.randbelow(900000) + 100000}"
    try:
        (BASE_DIR.parent / ".web_pin").write_text(pin, encoding="utf-8")
    except Exception:
        pass
    return pin
WEB_PIN = _load_or_make_pin()

# --- Google OAuth ---
GOOGLE_CREDENTIALS_FILE = str(BASE_DIR.parent / "google_credentials.json")
GOOGLE_TOKEN_FILE = str(BASE_DIR.parent / "google_token.json")

# --- Gmail personal context (IMAP, stdlib) ---
# App password (NOT your login password) from https://myaccount.google.com/apppasswords
# Save the 16-char password to D:\jarvis\.gmail_creds (gitignored) or env GMAIL_APP_PASSWORD.
GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS", "atlurisatheesh93@gmail.com").strip()
GMAIL_APP_PASSWORD = _load_secret("GMAIL_APP_PASSWORD", ".gmail_creds")

# --- Phone control (Phase 5) ---
# winget-installed platform-tools location; falls back to "adb" on PATH.
_ADB_WINGET = (Path(os.environ.get("LOCALAPPDATA", "")) /
               "Microsoft" / "WinGet" / "Packages" /
               "Google.PlatformTools_Microsoft.Winget.Source_8wekyb3d8bbwe" /
               "platform-tools" / "adb.exe")
try:
    _ADB_AVAILABLE = _ADB_WINGET.is_file()
except OSError:
    # Some restricted Windows sessions deny stat() under the Winget package
    # folder. ADB can still be available on PATH, so never block startup here.
    _ADB_AVAILABLE = False
ADB_PATH = str(_ADB_WINGET) if _ADB_AVAILABLE else (shutil.which("adb") or "adb")

# ===== BEAST upgrades =====

# Hands-free listener (jarvis_ai.listen): require saying the assistant name before a
# command so it ignores background chatter. False = respond to any speech.
REQUIRE_TRIGGER = True

# Ultra mode reflexes: allow safe playback controls like "stop" and "pause"
# without the wake word, so music can be stopped like Siri/Alexa.
WAKE_FREE_MEDIA_CONTROLS = True
# Siri/Alexa-style safety: do not answer normal questions unless the wake word
# was heard or an active follow-up session is open. Keep only urgent media stop
# controls wake-free.
WAKE_FREE_STATUS_QUESTIONS = os.environ.get("WAKE_FREE_STATUS_QUESTIONS", "false").lower() == "true"

# Continuous conversation: after a reply, listen for a follow-up without
# needing "Hey Leha" again, for this many seconds (0 = off).
#
# Production default stays OFF until the wake detector + echo handling are
# proven in real rooms. This prevents background conversation from becoming a
# command after one successful Leha turn.
FOLLOWUP_SECONDS = int(os.environ.get("FOLLOWUP_SECONDS", "0"))
# A bare wake word ("Leha") is different from a completed command. After she
# answers "Yes, Sir?", keep the gate open briefly for the user's actual request.
WAKE_ONLY_FOLLOWUP_SECONDS = int(os.environ.get("WAKE_ONLY_FOLLOWUP_SECONDS", "30"))
# Safety gate: after a bare wake ("Leha" -> "Yes, Sir?"), local/reflex
# commands are accepted, but unclear text is not sent to the cloud brain unless
# the user includes the wake word again. This prevents random room audio from
# becoming tool calls.
FOLLOWUP_BRAIN_ENABLED = os.environ.get("FOLLOWUP_BRAIN_ENABLED", "false").lower() == "true"
CONVERSATION_MAX_TURNS = 6
CONVERSATION_REHYDRATE_TURNS = int(os.environ.get("CONVERSATION_REHYDRATE_TURNS", "4"))
CONVERSATION_IGNORE_TEST_ARTIFACTS = os.environ.get(
    "CONVERSATION_IGNORE_TEST_ARTIFACTS", "true"
).lower() == "true"

# Voice-activity capture: stop recording after this much silence instead of
# a fixed window. Tune SILENCE_RMS up if it cuts you off, down if it hangs.
USE_VAD = True
MAX_COMMAND_SECONDS = 12
# 350ms cut people off mid-sentence: a natural pause before a place name
# ("go to ... Tirupati") ended the recording early. 800ms survives normal
# thinking pauses while still feeling responsive. Lower if she hangs too long
# after you finish, raise if she still cuts you off.
SILENCE_MS = int(os.environ.get("SILENCE_MS", "800"))
SILENCE_RMS = 80             # int16 RMS threshold; low because laptop mic input is quiet
VAD_START_MULTIPLIER = float(os.environ.get("VAD_START_MULTIPLIER", "1.8"))

# --- Ultra beat mode ---
EARCON_ENABLED = True
# Without validated acoustic echo cancellation, listening while Leha speaks can
# feed her own reply back into the mic and create a second response. Keep this
# OFF in production. The guarded barge-in code remains available for explicit
# headset/AEC experiments.
BARGE_IN_ENABLED = False
# When True, echo self-trigger detection auto-disables barge-in for the session
# after BARGE_IN_ECHO_LIMIT false interruptions inside BARGE_IN_ECHO_WINDOW_S.
AUTO_DISABLE_BARGE_IN_ON_ECHO = True
BARGE_IN_ECHO_LIMIT = 2
BARGE_IN_ECHO_WINDOW_S = 60.0
VAD_CALIBRATION_SECONDS = 1.5
BARGE_IN_RMS_BOOST = 2.0
ASSISTANT_EARCON_FREQ = 1200
ASSISTANT_EARCON_DUR_MS = 120
# The listener writes a lightweight state line at this interval so a stalled
# microphone or cloud request is visible in logs and the health command.
HEARTBEAT_SECONDS = 30
MIC_RECOVERY_MAX_SECONDS = 20

# Optional rough owner voice gate. Say "Leha train my voice" first, then set
# SPEAKER_VERIFY_ENABLED=True if you want sensitive commands to require your voice.
SPEAKER_VERIFY_ENABLED = False
SPEAKER_VERIFY_THRESHOLD = 0.86
SENSITIVE_ACTIONS = {"lock", "shell", "files", "phone", "type", "screenshot"}

# RAG embeddings
EMBED_MODEL = "nomic-embed-text"

# Screen OCR — set to tesseract.exe path if not on PATH
TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# run_script safety: only scripts under this dir may run by voice
SCRIPT_DIR = str(BASE_DIR.parent / "scripts")

# Universal shell: allow run_command (PowerShell) — true do-anything power.
# Your own PC, single user. Set False to disable arbitrary commands.
ALLOW_SHELL = True

# Daily briefing hour (24h)
BRIEF_HOUR = 6

# Routines / macros: name -> list of steps
ROUTINES = {
    "good morning": [
        {"action": "say", "text": "Good morning, Sir."},
        {"action": "open_app", "name": "chrome"},
    ],
    "work": [
        {"action": "open_app", "name": "code"},
        {"action": "open_app", "name": "chrome"},
    ],
    "work mode": [
        {"action": "say", "text": "Work mode on, Sir."},
        {"action": "open_app", "name": "code"},
        {"action": "open_app", "name": "chrome"},
    ],
    "movie mode": [
        {"action": "say", "text": "Movie mode, Sir."},
        {"action": "open_url", "url": "https://www.youtube.com"},
    ],
    "leaving home": [
        {"action": "say", "text": "Leaving home. Safe travels, Sir."},
    ],
    "good night": [
        {"action": "say", "text": "Good night, Sir."},
    ],
}

# --- Orchard / farm-robo wiring (the killer feature) ---
FARM_ROBO_DIR = r"D:\farm-robo\farm_robot_ai"
FARM_ROBO_PYTHON = r"D:\farm-robo\farm_robot_ai\.venv\Scripts\python.exe"
# Farm location for weather (default: approx Andhra Pradesh; set yours)
FARM_LAT = 16.5
FARM_LON = 80.6


def _apply_pro_settings_file() -> None:
    """Apply dashboard-owned settings after all defaults are defined."""
    path = MEMORY_DIR / "pro_settings.json"
    if not path.exists():
        return
    try:
        import json
        data = json.loads(path.read_text(encoding="utf-8"))
        if "custom_wake_threshold" in data:
            globals()["CUSTOM_WAKE_THRESHOLD"] = max(0.50, min(0.9999, float(data["custom_wake_threshold"])))
        if "barge_in_enabled" in data:
            globals()["BARGE_IN_ENABLED"] = bool(data["barge_in_enabled"])
        if "aec_enabled" in data:
            globals()["AEC_ENABLED"] = bool(data["aec_enabled"])
        if "proactive_max_spoken_per_hour" in data:
            globals()["PROACTIVE_MAX_SPOKEN_PER_HOUR"] = max(0, min(60, int(data["proactive_max_spoken_per_hour"])))
        if "quiet_hours_start" in data:
            globals()["PROACTIVE_QUIET_HOURS_START"] = str(data["quiet_hours_start"])
        if "quiet_hours_end" in data:
            globals()["PROACTIVE_QUIET_HOURS_END"] = str(data["quiet_hours_end"])
    except Exception:
        pass


_apply_pro_settings_file()
