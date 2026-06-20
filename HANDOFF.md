# JARVIS — Full Handoff & Status (for Antigravity)

Offline-first personal voice assistant. Local brain + tools, browser/native mic,
cloud STT (Groq, free). This doc = complete state: what works, what's broken,
what remains, how to run, and a prioritized improvement roadmap.

Last updated: 2026-06-20.

---

## 0. TL;DR — current state
- **Brain + 44 tools: WORKS** (local Ollama qwen2.5:3b, tool-calling).
- **Crop disease diagnosis: WORKS, REAL** (bridges to D:\farm-robo trained models).
- **STT: WORKS, accurate** via Groq cloud `whisper-large-v3-turbo` (free key).
- **Mic capture: WORKS** two ways — browser (getUserMedia) and native always-open stream.
- **TTS: WORKS** (Windows System.Speech via PowerShell in mouth.py).
- **Wake word / conversation flow: PARTLY WORKS** — this is the main remaining work
  (trigger gating + echo + endpointing). Details in §5–7.

The hard mic problems are SOLVED (Jabra USB headset + Groq STT). What remains is
**conversation UX polish**, not capture or accuracy.

---

## 1. How to run

```bash
cd D:\jarvis
python setup_check.py                 # verify deps/ollama/mic

# voice, always-on (Alexa-style, native) — PRIMARY
python -m jarvis_ai.listen

# voice via browser (one click to arm mic, then hands-free VAD)
python -m jarvis_ai.webserver         # open http://127.0.0.1:8001 in Chrome

# typed (100% reliable, no mic)
python -m jarvis_ai.chat --speak

# push-to-talk (press Enter, speak)
python -m jarvis_ai.ptt
```
Stop a running instance: `Stop-Process -Name python -Force` (PowerShell).
Always launch with `python -u` so logs flush.

---

## 2. Architecture / data flow
```
mic (Jabra USB headset, native 44.1/48k)
  → capture: jarvis_ai/audio.py  (scipy resample → 16k, VAD segment, normalize)
      • record_command()      : one utterance per call (used by ptt)
      • stream_utterances()   : ONE always-open stream, yields utterances (used by listen)
  → STT: jarvis_ai/ears.py
      • STT_ENGINE="groq" → Groq cloud whisper-large-v3-turbo (accurate, ~1s)
      • STT_ENGINE="local" → faster-whisper on CPU (offline, less accurate)
  → wake/trigger + conversation window: listen.py / webserver.py
  → brain: jarvis_ai/brain.py  (Ollama qwen2.5:3b, tool-calling, 5 rounds)
      → skills/*  (44 tools)
  → TTS: jarvis_ai/mouth.py  (Windows System.Speech) → speakers/headset
```

---

## 3. File map
```
jarvis_ai/
  config.py        ALL settings (model, STT engine, mic, thresholds, key loader). READ THIS FIRST.
  audio.py         mic capture: record_command() + stream_utterances() (always-open). scipy resample.
  ears.py          STT: Groq cloud OR local faster-whisper. _groq() has a `prompt` bias string.
  mouth.py         TTS via PowerShell System.Speech (strips non-ascii to avoid charmap crash).
  brain.py         Ollama chat + tool loop. keep_alive=30m, num_predict=80.
  listen.py        ALWAYS-ON voice loop (Alexa-style). trigger gate + 25s conversation window + mute-while-speaking.
  webserver.py     FastAPI: serves web/index.html, /api/voice (wake logic server-side), /api/text.
  web/index.html   browser UI: getUserMedia + client VAD + speechSynthesis.
  ptt.py           push-to-talk REPL.
  chat.py          typed REPL (--speak optional).
  scheduler.py     reminders + 6am morning brief (own TTS thread).
  rag.py           ChromaDB + nomic-embed-text RAG over docs.
  memory.py        JSON long-term facts.
  wake.py          openwakeword path — DEAD on this machine (see §7), don't use.
  skills/          system, files, web, media, notes, phone, reminders, routines,
                   desktop(OCR/clipboard/run_script), docs(RAG), farm, universal(run_command/calculate/hotkey)
.groq_key          gitignored Groq API key file (config reads it if env GROQ_API_KEY unset)
diag_*.py          mic/STT/wake diagnostics (see §9)
SETUP.md, JARVIS_BUILD_PLAN.md
```

---

## 4. WHAT WORKS (verified this session)
- `brain.ask("18% of 2450")` → calls `calculate` → **441** ✅
- `brain.ask("free disk space")` → `run_command` → **138.6 GB** ✅
- General Q (no tool), routines, reminders, RAG ✅
- `farm.diagnose_leaf(mango.jpg)` → **"Sooty Mould 64% + Jeevamrutham/Neem organic remedy"** (REAL torch models via subprocess to D:\farm-robo\.venv) ✅
- Groq STT accurate: heard "I am going to Chrome browser", "I'll tell you a joke" verbatim ✅
- Always-open mic stream yields utterances continuously ✅
- TTS speaks through headset ✅
- Web UI text endpoint end-to-end ✅

---

## 5. WHAT'S BROKEN / REMAINING (prioritized)

### P0 — Conversation flow / wake-word UX (the real remaining work)
Symptom: user speaks commands, nothing happens. Log shows STT heard them perfectly,
but they had no "Jarvis" → `REQUIRE_TRIGGER=True` ignored them. The user's mental model
flip-flops: sometimes wants pure wake-word (ignore everything until "Jarvis"), sometimes
wants "just talk and it replies". DECIDE the UX with the user:
- **Option A (Alexa-like):** keep `REQUIRE_TRIGGER=True`. User MUST start with "Jarvis".
  Already implemented in listen.py + webserver.py with a 25s follow-up window.
- **Option B (open):** `REQUIRE_TRIGGER=False` → replies to every utterance. Simpler, but
  reacts to background speech.
Recommend A, and make the wake word reliable (see P1).

### P1 — Wake-word robustness
Whisper mangles "Jarvis" → jarvis/jarwe/jarbis/travis/etc. listen.py `_TRIGGERS` has a fuzzy
list. IMPROVE: (a) add more variants seen in logs; (b) consider a real client-side wake-word
engine (Picovoice Porcupine — free tier, browser+native, true low-power "Jarvis"/"Hey Jarvis"
keyword, far more reliable than Whisper-substring). Porcupine = the proper fix; needs a free
access key.

### P2 — TTS echo leak
Log showed "Yes sir." captured as input = JARVIS heard itself. listen.py mutes via
`state["muted"]` while speaking + drops frames in stream_utterances, but timing gaps let some
through. IMPROVE: (a) increase post-speak mute tail (currently 0.25s); (b) flush the mic queue
on un-mute; (c) proper Acoustic Echo Cancellation (hard in Python — `speexdsp`/WebRTC AEC, or
just rely on headset isolation). With a headset (not speakers) echo is minor.

### P3 — Latency
qwen2.5:3b on CPU ≈ 5–20s/reply. Acceptable but not instant. Options: keep 3b; or add a fast
cloud brain (Groq LLM — same key! `llama-3.3-70b` etc.) for instant+smart, fall back to local
3b offline. STT already cloud; making the brain cloud-optional would make the whole thing snappy.

### P4 — Endpointing / barge-in
Can't interrupt JARVIS mid-reply (mic muted while speaking). Real assistants support barge-in
(say wake word to cut it off). Needs AEC + always-listening during TTS. Nice-to-have.

---

## 6. NOT DONE / NOT WIRED (features built but unused)
- **Telegram bridge** (`telegram_bot.py`): code done, needs BotFather token in `JARVIS_TG_TOKEN`.
  Lets you use phone mic. Untested.
- **Phone control (ADB)** (`skills/phone.py`): needs USB debugging + adb on PATH. Untested.
- **Piper TTS**: `mouth.py` supports it; currently uses Windows System.Speech. Drop a Piper
  voice in `voices/` + set `TTS_ENGINE="piper"` for nicer voice.
- **RAG** (`docs.py`/`rag.py`): works but no docs ingested yet. `ingest_docs(folder)` to use.
- **Scheduler morning brief**: only runs inside listen.py/main.py loops, not webserver.
- **qwen2.5:7b benchmark** (`bench_models.py`): never run; 3b vs 7b numbers pending.

---

## 7. KNOWN DEAD ENDS (do NOT re-chase)
- **openwakeword** (`wake.py`, `main.py`): scored ~0.02 on this machine even with clean audio.
  Dead. Use listen.py (Whisper-trigger) or Porcupine instead.
- **Native PortAudio capture of the built-in Intel mic**: the **"Senary Audio" virtual driver**
  hijacks it → silence or clipped noise on all MME/WASAPI endpoints. SOLVED only by the
  **Jabra USB headset** (its own clean endpoint). Built-in mic = unusable; don't debug it.
- **Local small/base Whisper for accuracy**: workable but garbles on CPU; Groq cloud replaced it.

---

## 8. CONFIG REFERENCE (jarvis_ai/config.py)
```
BRAIN_MODEL        = "qwen2.5:3b"   # 7b = smarter+slower; needs `ollama pull`
BRAIN_NUM_PREDICT  = 80            # reply length cap
BRAIN_KEEP_ALIVE   = "30m"         # keep model warm
STT_ENGINE         = "groq"        # "local" for offline
GROQ_STT_MODEL     = "whisper-large-v3"  # or -turbo (faster)
GROQ_API_KEY       = env or .groq_key file
MIC_DEVICE         = "Jabra"       # name substring; indices shift
INPUT_GAIN         = 2.0
REQUIRE_TRIGGER    = True          # must say "Jarvis" (Alexa-style)
WHISPER_MODEL      = "small"       # local fallback only
ALLOW_SHELL        = True          # run_command can run any PowerShell
FARM_ROBO_DIR/PYTHON, FARM_LAT/LON
```
listen.py tuning: `_TRIGGERS`, conversation window (25s), `stream_utterances(silence_ms, start_rms)`.
web/index.html tuning: `START_RMS`, `SILENCE_MS`.

---

## 9. DIAGNOSTIC SCRIPTS (D:\jarvis)
- `diag_headset.py`  — record Jabra + transcribe (WORKS reference)
- `diag_mic_scan.py` — RMS of every input device
- `diag_stt.py`, `diag_wasapi2.py`, `diag_senary.py` — device-specific capture tests
- `diag_wake.py`     — openwakeword score probe (shows it's dead)
- `bench_models.py`  — 3b vs 7b latency + tool-call (RUN THIS for the model decision)
- `cap.wav`          — listen.py/audio.py saves last capture here (set `_SAVE_CAPTURE`) — listen to debug audio

---

## 10. MODELS & COST
- Brain: qwen2.5:3b (local, free). Ceiling on 16GB/CPU ≈ 14B; 32B+ won't fit.
- STT: Groq whisper-large-v3-turbo — **free tier**, fast, accurate. Needs internet.
- Embeddings: nomic-embed-text (local, free).
- Hardware: 16GB RAM, Intel Core 7 240H, NO GPU. CPU-only inference.

---

## 11. SECURITY
- `.groq_key` holds the Groq key in plaintext, **gitignored**. Rotate the key at groq.com if it
  was ever pasted in chat/shared. Never commit it.
- `ALLOW_SHELL=True` → `run_command` runs arbitrary PowerShell. Fine for single-user local use;
  set False to disable.

---

## 12. SUCCESS CRITERIA (definition of "done" for voice)
1. Say "Jarvis, what time is it" (one breath) → correct transcription → correct answer spoken. ✅ achievable now
2. Say "Jarvis" → "Yes Sir?" → (pause) → "what's the weather" → answered, command NOT lost. ← verify the always-open stream fixed this
3. Background speech / JARVIS's own voice → ignored (no false triggers, no self-capture). ← P2 echo work
4. Reply latency acceptable (<5s ideal). ← P3, consider Groq LLM brain

## 13. RECOMMENDED NEXT STEPS (in order)
1. Confirm UX with user: Alexa-style (REQUIRE_TRIGGER=True) — say "Jarvis" first. Train the user on this.
2. Add **Porcupine** wake word (browser + native) for reliable "Jarvis" detection. (free key)
3. Fix TTS echo (mute tail + queue flush) — or rely on headset.
4. Offer **Groq LLM brain** (cloud, same key) for instant replies; keep local 3b as offline fallback.
5. Run `bench_models.py`; decide 3b vs 7b.
6. Wire Telegram (phone mic) if user wants mobile.
