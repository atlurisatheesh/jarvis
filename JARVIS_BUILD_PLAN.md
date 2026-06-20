# PROJECT JARVIS — Personal Offline AI Assistant

**Owner:** Satheesh
**Goal:** Voice-controlled offline assistant that controls my Windows laptop and my Android phone, free, no cloud, no API keys.
**Created:** 2026-06-19
**Status:** Planning complete → ready for Phase 0

---

## 0. Reality check (read first, re-read when frustrated)

Iron Man's JARVIS is fiction (AGI). What I am building is real and useful:

> Voice in → wake word → speech-to-text → local LLM brain decides what to do → runs a Python function I wrote → speaks the answer back.

It is **as smart as the model + as capable as the tools I give it**. Every skill ("open Chrome", "what's the weather", "send a WhatsApp") is a function. The assistant is the glue: voice + reasoning + functions. No magic, no consciousness — but a genuinely powerful hands-free remote for my machine.

**What is realistic (free, offline):**
- Talk to it, it answers (local LLM chat). ✅
- Control the laptop: open apps/files, web search, type, volume, system info, music, timers. ✅
- Remember me and my preferences. ✅
- Control my Android from the laptop over USB/WiFi (open apps, tap, type, SMS, settings). ✅
- Talk to laptop-JARVIS *from* my phone (Telegram / web). ✅

**What is NOT realistic (drop these expectations):**
- The phone running the full brain itself (no RAM for it, free/offline). ❌
- "Control literally everything" with zero setup. Each capability is a coded skill. ❌
- General intelligence / improvising beyond its tools. ❌

---

## 1. My hardware (locks the choices)

| Part | Value | Effect on build |
|---|---|---|
| RAM | 16 GB | Comfortable. 7B model + Whisper + Piper fit. |
| CPU | Intel Core 7 240H (10c/16t) | Strong. Runs the brain on CPU. |
| GPU | Intel integrated (no NVIDIA) | **No GPU acceleration** → replies stream at ~6–12 words/sec. Usable, not instant. |
| OS | Windows 11 Home | All tools supported. |
| Phone | Android | Control + remote both possible. |

**Brain model decision:**
- Default: **Qwen2.5 7B Instruct (Q4)** — best small tool-caller, ~4.7 GB, good answers.
- If too slow for me: **Qwen2.5 3B** — snappier, slightly dumber.
- Whisper: **tiny** (fast) → upgrade to **base** if accuracy poor.

---

## 2. The stack (all free, all offline)

| Layer | Tool | Install |
|---|---|---|
| Model runner (brain engine) | **Ollama** | ollama.com installer |
| Brain model | **Qwen2.5 7B / 3B** | `ollama pull qwen2.5:7b` |
| Wake word ("Hey Jarvis") | **openwakeword** | `pip install openwakeword` |
| Ears (speech→text) | **faster-whisper** | `pip install faster-whisper` |
| Mouth (text→speech) | **Piper** (human-ish voice) | piper-tts + a voice model |
| Mic / audio | **sounddevice + numpy + soundfile** | `pip install sounddevice numpy soundfile` |
| Memory (later) | **ChromaDB** | `pip install chromadb` |
| Phone bridge (later) | **python-telegram-bot** | `pip install python-telegram-bot` |
| Phone control (later) | **scrcpy + ADB (platform-tools)** | download zips |

> Note: **OpenCode is NOT the brain.** It is a coding agent that itself runs on Ollama. JARVIS talks to Ollama directly. Keep OpenCode for coding only.

---

## 3. Project folder layout (target)

```
D:\jarvis\
  jarvis_ai\
    main.py              # entry: wake-word loop
    config.py            # settings (model name, thresholds, paths)
    brain.py             # talks to Ollama, handles tool-calling
    ears.py              # faster-whisper STT
    mouth.py             # Piper TTS
    wake.py              # openwakeword listener
    skills\
      __init__.py        # registry of all tools
      system.py          # open apps, volume, shutdown, info
      files.py           # open/search files & folders
      web.py             # web search, open URL
      media.py           # play/pause music
      phone.py           # (Phase 5) ADB control of Android
    memory\              # (Phase 3) ChromaDB store
    voices\              # Piper voice model files
  requirements.txt
  JARVIS_BUILD_PLAN.md   # this file
```

---

## 4. Phased build plan

Each phase ends with something that WORKS. Don't skip ahead.

### Phase 0 — Foundation (install + verify)  ·  ~30–45 min
1. Install Ollama, `ollama pull qwen2.5:7b` (and `:3b` as backup).
2. Verify: `ollama run qwen2.5:7b "say hello as JARVIS"` returns text.
3. `pip install` the audio + STT libs.
4. Download a Piper voice (e.g. a clear English voice).
5. Create folder layout + `config.py`.
**Done when:** Ollama answers in terminal, mic records, Piper speaks a test line.

### Phase 1 — Voice loop (talk to it)  ·  core
- Wake word "Hey Jarvis" → record command → Whisper transcribes → send to Ollama → Piper speaks reply.
- Proper version of the PDF code, bugs fixed:
  - Whisper model loaded **once** at startup (PDF reloaded it every trigger = lag).
  - No `except: pass` — errors logged.
  - Audio capture via a **queue**, not blocking inside the callback.
**Done when:** I say "Hey Jarvis, who are you?" and it answers in voice.

### Phase 2 — Laptop control (the real power)  ·  ~15 skills
- Give the LLM **tool-calling**: it outputs which function + arguments, Python runs it.
- Starter skills: open app, close app, open file/folder, search web, type text, set volume, screenshot, system info (battery/CPU/RAM), play/pause media, timer/reminder, tell time/date, lock PC.
**Done when:** "Hey Jarvis, open Chrome and search for mango leaf disease" actually does it.

### Phase 3 — Memory + personality  ·
- ChromaDB stores facts about me + past conversations → it remembers across restarts.
- Personality: calls me by name, concise JARVIS tone, confirms before risky actions (shutdown, delete).
**Done when:** it recalls something I told it yesterday.

### Phase 4 — Phone as remote (reach it from anywhere)  ·
- Telegram bot: I send a text or voice note from my Android → laptop-JARVIS processes → replies in Telegram.
- Free, works over internet OR same WiFi (local-only mode possible).
**Done when:** I message JARVIS from my phone and it controls the laptop + replies.

### Phase 5 — Control the Android  ·  (Android-only, I have this)
- Enable USB debugging on phone. Connect via USB or WiFi ADB.
- `scrcpy` mirrors/controls screen; ADB skills: open app, tap, type, SMS, toggle WiFi/Bluetooth/airplane, volume, screenshot.
- New skills in `skills/phone.py`, callable by voice from the laptop.
**Done when:** "Hey Jarvis, open WhatsApp on my phone and message Amma" works.

---

## 5. Effort / risk per phase

| Phase | Difficulty | Risk | Payoff |
|---|---|---|---|
| 0 Foundation | Easy | Low (install hiccups) | Required |
| 1 Voice loop | Medium | Mic/wake-word tuning | High — it's alive |
| 2 Laptop control | Medium | Tool-calling reliability on 7B | Highest |
| 3 Memory | Medium | Low | Quality of life |
| 4 Phone remote | Medium | Telegram setup | High — mobility |
| 5 Android control | Harder | ADB setup, per-app quirks | High — the "wow" |

**Biggest real risks:**
1. **CPU latency** — 7B on no-GPU may feel slow. Mitigation: use 3B, keep replies short, stream audio as it generates.
2. **Tool-calling accuracy** — small models sometimes pick wrong function. Mitigation: tight tool descriptions, confirmation on risky actions.
3. **Wake-word false triggers** — tune threshold (0.3 → 0.4) per PDF guidance.
4. **Android per-app control is fiddly** — taps depend on screen layout. Start with reliable ADB intents (open app, SMS), not pixel taps.

---

## 6. Cost: ₹0. No subscriptions, no API keys, no cloud. 100% local.

---

## 7. Next action
Phase 0. On approval: install Ollama + libs, pull the model, verify each piece, then build Phase 1 voice loop.
