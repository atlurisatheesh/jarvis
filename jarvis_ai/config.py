"""Central configuration for Leha. Tweak values here, not in code."""
import os
import shutil
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
VOICES_DIR = BASE_DIR / "voices"
MEMORY_DIR = BASE_DIR / "memory_store"

# --- Brain ---
# Engine: "groq" (cloud, instant), "local" (Ollama on CPU), "auto" (Groq → local fallback)
BRAIN_ENGINE = "auto"
GROQ_BRAIN_MODEL = "llama-3.1-8b-instant"   # higher daily limit + faster than 70b
# Only send these tools to the cloud brain (keeps each request small -> under
# the free-tier 6000 tokens/min limit). Reflexes in assistant_core handle the
# rest locally. Empty/None = send all (will hit rate limits).
GROQ_TOOL_ALLOWLIST = [
    "calculate", "web_search", "open_app", "close_app", "play_youtube",
    "system_info", "get_weather", "set_reminder", "remember_fact",
    "run_command", "diagnose_leaf", "lock_pc",
    # Windows system control
    "sleep_pc", "restart_pc", "shutdown_pc", "hibernate_pc", "logoff_pc",
    "get_processes", "kill_process",
    "show_desktop", "minimize_all", "snap_window", "switch_to_app",
    "set_brightness", "turn_off_screen", "eject_usb",
    "get_ip", "toggle_wifi", "list_wifi",
    "dark_mode", "set_wallpaper", "battery_report", "find_large_files",
    # Screen awareness + personal context (Siri-AI parity)
    "read_screen", "see_screen", "read_clipboard", "set_clipboard",
    "search_file_contents", "recent_files", "find_anything", "ask_docs",
    "search_email", "recent_email", "unread_email",
    # Phone (Android via ADB)
    "phone_status", "phone_open_app", "phone_send_sms", "phone_key",
    "phone_type", "phone_screenshot", "phone_notifications", "phone_ring",
    "phone_whatsapp", "phone_read_sms", "phone_unread_sms", "phone_call",
]
GROQ_TIMEOUT_SECONDS = 12
# Do not block the always-on microphone while retrying a throttled cloud model.
# A short spoken status is better than a frozen assistant.
GROQ_RATE_LIMIT_RETRY_SECONDS = 0
GROQ_RATE_LIMIT_REPLY = "My fast brain is busy for a moment, Sir. Please try again."

OLLAMA_HOST = "http://127.0.0.1:11434"
# Local brain model (used when BRAIN_ENGINE="local" or as auto fallback).
BRAIN_MODEL = "qwen2.5:3b"
# Cap reply length -> faster finish + shorter spoken answers.
BRAIN_NUM_PREDICT = 80       # enough for a full spoken sentence
# Keep the model loaded in RAM so it doesn't reload (adds latency) between turns.
BRAIN_KEEP_ALIVE = "30m"
ASSISTANT_NAME = "Leha"
USER_NAME = "Sir"
ASSISTANT_MODE = "ultra"

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
    "ALWAYS use the calculate tool for any arithmetic instead of doing it in your head. "
    "To check or change something on the computer (disk, processes, files, settings), call "
    "run_command instead of asking the user to provide it. "
    "Answer in ONE short sentence, max ~15 words, no markdown. Give the answer directly -- "
    "NO filler, NO 'if you need anything else', NO restating the question. "
    "Never invent tool output. If truly ambiguous, ask one short question."
)

# --- Ears (speech-to-text) ---
# "auto" prefers Deepgram, then OpenAI, then Groq, then local Whisper based
# on available keys. Deepgram is the active low-latency ears provider.
STT_ENGINE = os.environ.get("STT_ENGINE", "deepgram").strip().lower()
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
WHISPER_LANG = "en"           # set None for auto-detect (Telugu/Hindi, slower)

# Optional cloud speech-to-text providers. Keep keys in environment variables
# or local ignored files next to the project: .deepgram_key / .openai_key.
DEEPGRAM_API_KEY = _load_secret("DEEPGRAM_API_KEY", ".deepgram_key")
DEEPGRAM_STT_MODEL = os.environ.get("DEEPGRAM_STT_MODEL", "nova-3").strip()
OPENAI_API_KEY = _load_secret("OPENAI_API_KEY", ".openai_key")
OPENAI_STT_MODEL = os.environ.get("OPENAI_STT_MODEL", "gpt-4o-mini-transcribe").strip()
STT_REQUEST_TIMEOUT_SECONDS = 8
# Keep an always-on assistant responsive. Set True only when local Whisper is
# already warm and you explicitly prefer a slow offline fallback.
STT_CLOUD_FALLBACK_TO_LOCAL = False

# --- Wake word / audio ---
SAMPLE_RATE = 16000

# --- Porcupine wake word (highly recommended — replaces Whisper-substring) ---
# Get free access key at: https://console.picovoice.ai/
# Then pip install pvporcupine
PORCUPINE_ACCESS_KEY = os.environ.get("PORCUPINE_ACCESS_KEY", "").strip()
# Optional: path to custom "Leha" .ppn keyword file from console.picovoice.ai
# Without it, falls back to built-in "jarvis" keyword (say "Jarvis" to wake)
PORCUPINE_KEYWORD_PATH = os.environ.get("PORCUPINE_KEYWORD_PATH", "").strip()

# openwakeword (offline, no signup — only works with clean mic, e.g. Jabra USB)
# Set OWW_ENABLED=True only after confirming: python diag_oww.py shows rms > 100
OWW_ENABLED = False   # <- set True to activate; needs Jabra plugged in
OWW_MODEL_NAME = "hey_jarvis"
OWW_THRESHOLD = 0.5   # 0.3=sensitive, 0.7=strict

# Mic selection + gain. The Windows DEFAULT mic captured silence on this laptop;
# device 13 ("Microphone Array 4") was the only live one in the scan. Set the
# index here (run diag_mic_scan.py to re-check; indices can change on reboot).
MIC_DEVICE = "Jabra"          # name substring (robust to index changes); None = default
INPUT_GAIN = 2.0              # mild boost; headset speech rms ~300

# --- Command capture ---
COMMAND_SECONDS = 5           # how long to listen after wake

# --- Mouth (text-to-speech) ---
# "edge" is the live/instant human voice.
# "hf" calls a warm Hugging Face Inference Endpoint.
# "clone" uses the supplied reference recordings. It is slower on CPU, but
# keeping it strict avoids mixing a generic system/Edge voice into Leha replies.
TTS_ENGINE = "clone"
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
CLONE_TTS_STRICT = True       # cloned voice only; never mix fallback voices
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
OUTPUT_DEVICE = None  # set to device index if wrong speaker used

# --- Telegram bridge (Phase 4) — talk to Leha from your phone, anywhere ---
# Get a token from @BotFather (/newbot), then either set env JARVIS_TG_TOKEN
# or save the token to D:\jarvis\.tg_token (gitignored, same as .groq_key).
TELEGRAM_TOKEN = _load_secret("JARVIS_TG_TOKEN", ".tg_token")
# Your numeric Telegram user id(s) from @userinfobot. Empty list = allow anyone
# (NOT recommended — anyone who finds the bot could control your laptop).
TELEGRAM_ALLOWED_USERS = []

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

# Continuous conversation: after a reply, listen for a follow-up without
# needing "Hey Jarvis" again, for this many seconds (0 = off).
FOLLOWUP_SECONDS = 25

# Voice-activity capture: stop recording after this much silence instead of
# a fixed window. Tune SILENCE_RMS up if it cuts you off, down if it hangs.
USE_VAD = True
MAX_COMMAND_SECONDS = 12
SILENCE_MS = 650             # enough for natural pauses without clipping a request
SILENCE_RMS = 280            # int16 RMS threshold for "silence" (post-gain)

# --- Ultra beat mode ---
EARCON_ENABLED = True
BARGE_IN_ENABLED = True
VAD_CALIBRATION_SECONDS = 1.5
BARGE_IN_RMS_BOOST = 2.0
ASSISTANT_EARCON_FREQ = 1200
ASSISTANT_EARCON_DUR_MS = 120

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
}

# --- Orchard / farm-robo wiring (the killer feature) ---
FARM_ROBO_DIR = r"D:\farm-robo\farm_robot_ai"
FARM_ROBO_PYTHON = r"D:\farm-robo\farm_robot_ai\.venv\Scripts\python.exe"
# Farm location for weather (default: approx Andhra Pradesh; set yours)
FARM_LAT = 16.5
FARM_LON = 80.6
