# Changelog

All notable changes to Leha are recorded here. Format follows
[Keep a Changelog](https://keepachangelog.com/); versions follow semantic
versioning (MAJOR.MINOR.PATCH). The live version string is read from
`jarvis_ai/VERSION` into `config.LEHA_VERSION`.

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
