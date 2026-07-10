# Changelog

## [1.3.0] - 2026-07-10

Desktop reliability and response-pipeline release.

### Fixed
- Uses Deepgram's dedicated English + `Leha` keyterm path for idle wake audio,
  avoiding unstable auto-language detection before wake.
- Runs Deepgram wake-keyterm and Sarvam wake verification concurrently; either
  can recover the owner's call, but the result must still pass the strict gate.
- Runs Deepgram and Sarvam concurrently after wake and selects the fuller,
  non-noise transcript, fixing questions reduced to fragments such as `Kalam?`.
- Saves only the latest post-wake command audio in the ignored logs directory
  so failed recognition can be reproduced against every provider.
- Recognizes exact Greek `Leha` transliterations seen in live STT logs, while
  requiring independent Sarvam confirmation for ambiguous `yeah/yes/hello`.
- Removes the duplicate wake-hit configuration assignment and retains the
  evidence-backed two-hit safety gate.
- Separates idle wake VAD (`140`) from sensitive post-wake command VAD (`90`),
  preventing background chatter from monopolizing cloud transcription.
- Excludes the audible manual brain/mouth smoke script from automated pytest,
  preventing PortAudio crashes while the production listener owns the device.
- Routes streamed brain answers through ElevenLabs instead of accidentally
  falling through to the Windows system voice, eliminating that dual-voice path.
- Prevents a mid-stream ElevenLabs failure from changing speaker identity;
  Edge fallback is allowed only before cloned audio starts.
- Skips incomplete OpenWakeWord ONNX bundles instead of crash-looping when an
  external `.onnx.data` weights file is missing.
- Prevents provider failover after a streamed answer has already emitted text,
  eliminating duplicate spoken answers after a mid-stream failure.
- Isolates automated tests from production conversation memory and labels
  restart history so old tool actions cannot become the current request.
- Supervisor `--check` now evaluates the real startup health gate.
- Stream playback errors release the producer instead of hanging the listener.
- STT fallback is now per utterance; a silent Deepgram result can no longer
  permanently replace the primary ears provider or disable wake-biased retry.
- A clean bare wake now accepts exactly one non-noise dynamic follow-up before
  re-locking, fixing the live `Yes, Sir?` followed by no answer failure.
- Idle wake recovery skips the slow Sarvam rescue before Deepgram's dedicated
  wake-biased retry; Indian-language rescue remains active for commands.

### Changed
- The cloned `Yes, Sir?` wake acknowledgement is cached as local PCM/WAV after
  first generation, avoiding cloud latency and intermittent speech-state stalls.
- Fixed cloned phrases now play through Windows' native default audio endpoint
  with controlled `2.0x` gain and explicit playback-completion telemetry.
- Routes all Leha speech explicitly to the second active Senary speaker endpoint
  because the nominal Windows default completed silently on this laptop.
- ElevenLabs cloned speech now streams 24 kHz PCM directly to the selected
  output device, reducing time-to-first-audio and retaining interruption.
- Clone replacement tooling creates a private candidate first and never
  deletes or changes the working voice unless `--activate` is explicit.
- Brain token generation and sequential TTS playback now run concurrently
  through one bounded, cancellable voice queue.
- The dashboard reports the deployed hybrid wake model and measured results.
- Strict transcript wake remains enabled to block broad room-audio aliases.

### Verified
- 439 root desktop tests pass and Python compilation succeeds.
- The live listener loads `leha.onnx` and enters active wake listening.
- A short live Groq request produced first text in 0.49 seconds and completed
  in 0.57 seconds.

All notable changes to Leha are recorded here. Format follows
[Keep a Changelog](https://keepachangelog.com/); versions follow semantic
versioning (MAJOR.MINOR.PATCH). The live version string is read from
`jarvis_ai/VERSION` into `config.LEHA_VERSION`.

## [1.2.0] — 2026-07-09

Pro-mode pass: Leha-only wake, cloud-first brain order, Indian-language ears,
owner-voice phrase cache.

### Changed
- **Wake word is "Leha" only.** All "jarvis" / "hey jarvis" transcript wake
  triggers removed from `wake_phrases.py`. Indic-script Leha triggers stay.
- **Brain order for English turns is now Groq → Cloudflare → OpenAI → local
  Ollama.** Groq (llama-3.3-70b-versatile) has the lowest first-token latency,
  so spoken replies start faster. Local qwen2.5:3b is strictly the last
  offline fallback. Indian-language turns keep NVIDIA sarvam-m first.
- `TTS_ENGINE` and `CLONE_TTS_STRICT` are now environment-overridable;
  clone-synthesis failures fall back to the Edge neural voice instead of
  staying silent.

### Added
- **Sarvam saarika speech-to-text provider** in `ears.py`. Auto-detects
  Telugu, Hindi, Tamil, Kannada, Malayalam, and code-mixed speech. Runs as a
  fallback tier after Deepgram, and as an automatic rescue when Deepgram
  transcribes with confidence below `STT_DEEPGRAM_MIN_CONFIDENCE` (0.60) —
  Deepgram nova-3 has no Telugu/Tamil/Kannada support.
- **Owner-voice phrase cache.** `tools/prerender_clone_phrases.py` renders
  Leha's short fixed phrases ("Yes, Sir?", routine lines) once through the
  Chatterbox voice clone (reference: the owner's cleaned WhatsApp audio) into
  `voices/clone_cache/`. `mouth.py` plays a cached phrase instantly in the
  owner's cloned voice and uses Edge for dynamic answers — full-clone live TTS
  stays impractical on CPU (~60s/sentence).

## [1.1.0] — 2026-06-25

Phase 6–9 build-out. All additive and config-gated; no existing voice, brain,
TTS, wake, Google, or Android behavior was changed.

### Added
- **Phase 9 — Operations.** `jarvis_ai/VERSION` + this `CHANGELOG.md`;
  `config.LEHA_VERSION` reads the VERSION file. `scripts/run_tests.ps1`
  unified runner with a phase-by-phase pass/fail summary.
- **Phase 6 — `device_manager.py`.** Device pairing approval, session tokens
  with expiry, per-device request rate limiting, and per-device capability
  scoping. Disabled by default (`DEVICE_MANAGER_ENABLED=false`) so the current
  PIN-gated web/Android path is unchanged.
- **Phase 7 — `home_assistant.py`.** Scoped-token Home Assistant client that
  degrades gracefully to "not configured" when no token is present. Expanded
  `config.ROUTINES` with named routines (Good Morning, Work Mode, Movie Mode,
  Leaving Home, Good Night).
- **Phase 8 — `structured_memory.py` + `summarizer.py`.** Typed memory store
  (fact / preference / task / contact_note) with CRUD and retrieval by type;
  local extractive conversation summarizer that does not send history to the
  cloud. Existing flat `memory.py` left untouched.
- Tests: `test_phase6.py`, `test_phase7.py`, `test_phase8.py`, `test_phase9.py`.

### Fixed
- Flaky `test_augment_preserves_dtype` (asserted unchanged length while speed
  perturbation legitimately changes it).
- `test_wake_model.py` Windows `WinError 32` temp-file leaks (unclosed
  `mkstemp` descriptors).
- `wake_trainer._load_wav_16k` now decodes from an in-memory buffer so
  libsndfile never holds an OS file handle.

### Changed
- Scheduler reminders and the morning brief now route through the central
  `SpeechManager` (`self.speech`) instead of a raw `Mouth`, preventing a
  briefing from overlapping a command response.

## [1.0.0] — 2026-06-20

Initial tagged build: Phases 0–5. Always-on Windows voice loop, supervisor +
health, trained (disabled) wake model, latency/circuit-breaker layer, central
speech manager module, skill policy/audit/undo, Google read + two-step write,
Android/PWA client with PIN gate and remote-origin safety.
