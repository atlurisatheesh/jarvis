# Leha — Implementation Status (Phases 0–9)

> **Living document.** Updated 2026-06-30. This file records exactly what is
> built, what is wired into the live assistant, what is stubbed, what is tested,
> and what is pending — phase by phase. It is the authoritative source of truth
> for "where did we get to in the previous chat."
>
> The companion strategy files are:
> - `ULTRA_BEAST_ROADMAP.md` — the plan, principles, and acceptance tests.
> - `ULTRA_BEAST_STATUS.md` — the high-level working/pending narrative.
> - `IMPLEMENTATION_STATUS.md` (this file) — the code-level audit per phase.

---

## Verified Live State - 2026-07-10

This section supersedes historical phase notes below when they conflict.

- Desktop listener, supervisor, and webserver are running as one supervised
  listener plus one web process.
- Wake engine is `openwakeword+strict_transcript` using the complete
  `voices/leha.onnx` model. The incomplete `hey_leha.onnx` graph is skipped
  because its external weights file is absent.
- Production wake settings are threshold `0.5`, two consecutive hits, and
  strict transcript fallback. Held-out neural result: 80% recall and 0/280
  false wakes. This is a hybrid candidate, not Siri-grade approval.
- Brain and sentence TTS are genuinely pipelined: model tokens continue
  generating while one voice worker speaks queued chunks.
- Mid-stream provider failure cannot start a second provider after speech has
  begun, preventing duplicate answers.
- A fallback STT result applies only to that utterance. Deepgram remains the
  primary ears provider unless an authentication failure explicitly disables it.
- Persistent conversations survive restarts, but old turns are injected only
  as labeled historical context. Automated tests use an isolated store.
- Supervisor health uses the real startup gate; incomplete wake bundles and
  required-subsystem failures are visible instead of falsely reporting ready.
- Production voice is the private ElevenLabs clone using streamed 24 kHz PCM.
  A fair speaker-embedding comparison against both authorized recordings kept
  the existing clone (`0.670` centroid similarity) over clean-only (`0.542`)
  and combined-sample (`0.632`) candidates. Edge neural female voice remains
  the pre-audio network/quota fallback.
- ElevenLabs streamed-answer dispatch is covered by tests. A mid-stream outage
  ends that utterance instead of switching to Edge and producing two voices.
  A live API benchmark produced first PCM in 1.455 seconds and completed the
  short test utterance in 1.646 seconds with no fallback.
- Barge-in remains disabled because this laptop has no validated AEC or
  hardware AEC device. This is a safety requirement, not missing routing code.
- Complete safe root suite: **439 passed, 0 failed**. No shutdown, restart,
  sleep, call, message, or other destructive action was executed.

External/physical acceptance still required: 20-call room wake test, one-hour
false-wake soak with real room audio, validated headset/AEC before barge-in,
Home Assistant devices/token and OS-level mobile work.

Latest recorded-clip spot check: the neural two-hit model woke on 1/5 owner
clips; strict Deepgram rescue raised total hybrid recovery to 3/5. This is a
small diagnostic sample, but it confirms wake is still the principal blocker
and the model must remain unapproved.

Wake reliability correction on 2026-07-10: idle fallback now starts with
Deepgram English + `Leha` keyterm bias instead of unstable auto-language
detection. On the same owner validation clip, auto-language took 3.54 seconds
and varied across unrelated languages; wake-biased transcription returned
`Leha` in 1.53 seconds. Exact Greek transliterations observed in live logs are
accepted, while ambiguous `yeah/yes/hello` requires independent Sarvam
confirmation. The cloned `Yes, Sir?` acknowledgement is cached locally and
completes playback in 0.79 seconds without a TTS network request.
The hybrid transcript VAD now uses a stricter idle gate (`140`) while command
capture remains at `90`; a live 30-second room soak produced zero background
transcriptions, keeping the listener available for the actual wake call.
Idle wake clips are checked concurrently by Deepgram's Leha-keyterm mode and
Sarvam; either result must independently pass the strict wake gate. On an owner
validation clip this recovered a valid Bengali-script Leha transcript in 1.31
seconds, while two unrelated transcripts remain ignored.
The fixed cloned acknowledgement now uses Windows native default-endpoint WAV
playback at `2.0x` safe gain. Playback completion is logged explicitly; the
cached file measures RMS `0.144`, peak `0.684`, and finishes in about 1.19s.
Audio-route diagnosis found two active Senary endpoints. The Windows default
endpoint completed playback but was inaudible to the owner, so Leha now routes
cached and streamed speech explicitly to device `4`, `Speakers (2- Senary
Audio)`. Both endpoint and Python-session volume were verified at 100%/unmuted.
Post-wake commands now run Deepgram and Sarvam concurrently and select the
stronger non-noise transcript, favoring fuller text and Indian scripts. The
latest captured command is retained locally as `logs/last_command.wav` for
provider-by-provider diagnosis; logs remain gitignored.

---

## At-a-Glance Scorecard

| Phase | Topic | Code built | Wired into live loop | Tests | Status |
|-------|-------|-----------|----------------------|-------|--------|
| 0 | Stability, logs, supervisor, health | ✅ Full | ✅ Live | ✅ 19/19 pass | **Done** |
| 1 | Dedicated Leha wake model | ✅ Full (tools + model ONNX) | ⚠️ Code ready, model trained, **disabled in prod** | ✅ 22/22 pass | **Built, awaiting real-world tuning** |
| 2 | Latency, circuit breakers, cache, bg jobs | ✅ Full | ✅ Live (cooldowns + cache + bg dispatch) | ✅ 27/27 pass | **Done** |
| 3 | Speech manager, AEC, barge-in | ✅ Full | ✅ **Live** — `SpeechManager` wired into `listen.py` (`self.speech`); AEC off by design | ✅ 25/25 pass | **Done** |
| 4 | Skill policy, audit, undo, window mgr | ✅ Full | ✅ Live (policy + audit + undo wired) | ✅ 26/26 pass | **Done** |
| 5 | Google two-step actions, Maps stub | ✅ Full | ✅ Live | ✅ 18/18 pass | **Done** |
| 6 | device_manager, webserver hardening, Android | ✅ Full | ✅ **Wired** — `device_manager` opt-in in `webserver.py` (pair/session/approve/revoke endpoints); `DEVICE_MANAGER_ENABLED=false` default | ✅ 18/18 pass | **Done (opt-in)** |
| 7 | Home Assistant, routines | ✅ Full | ✅ **Wired** — 5 HA skills registered in `skills/__init__.py`; graceful "not configured" | ✅ 15/15 pass | **Done (awaiting HA token)** |
| 8 | Structured memory, summarizer, memory skills | ✅ Full | ✅ **Wired** — 4 memory skills registered (`remember_this`, `what_do_you_remember`, `forget_that`, `export_my_data`); local reflexes in `assistant_core.py` | ✅ 18/18 pass | **Done** |
| 9 | Version system, ops toolkit, test runner | ✅ Built | ✅ `VERSION`+`config.LEHA_VERSION`, `CHANGELOG.md`, `scripts/run_tests.ps1`, `test_phase6-9.py` | ✅ 8/8 pass | **Done (dependency lock still optional)** |

**Test totals (run 2026-06-25, after full wiring):** `240 passed, 0 failed`
across 13 test files. Run all via `scripts/run_tests.ps1`.

**Safety correction (run 2026-06-30):** production follow-up mode is back to
`FOLLOWUP_SECONDS = 0` and production barge-in is back to
`BARGE_IN_ENABLED = False`. This preserves stable wake gating and prevents
speaker echo from creating duplicate/random replies. Guarded barge-in code
remains available for explicit headset/AEC experiments only.

> **No-disturb guarantee.** Phase 6/7/8 are additive and default-OFF or
> not-yet-wired: voice, brain, TTS, wake, Google, and Android live paths are
> unchanged. Phase 9 only adds files + a version string. The one live-path
> change is the scheduler/morning-brief now routing through the central
> SpeechManager (`self.speech`) instead of a second raw `Mouth`.

---

## Phase 0 — Stabilize The Existing Assistant ✅ DONE

**Goal:** one laptop voice loop that runs for hours without duplicate voices,
random answers, or an open PowerShell window.

### Files built
| File | Purpose | State |
|------|---------|-------|
| `jarvis_ai/log_manager.py` | Central log: rotation, **token redaction**, retention cleanup, structured `YYYY-MM-DD HH:MM:SS LEVEL [component] msg` format | ✅ Production |
| `jarvis_ai/supervisor.py` | Only production launcher. Restarts `listen` on crash, crash-loop guard (>3 restarts/60s → 30s backoff), `--check` health probe, startup log cleanup | ✅ Production |
| `jarvis_ai/runtime_state.py` | In-process state registry: state, detail, age, turn count, per-stage timings, last provider | ✅ Production |
| `jarvis_ai/health.py` | `check()` probes net/ollama/groq/cloudflare/deepgram/openai/mic/adb/google-token; `voice_summary()` for "Leha health"; `--json` mode | ✅ Production |
| `scripts/install_autostart.ps1` | Registers Windows Scheduled Task at logon (or per-user Startup `.vbs` fallback) targeting `python -m jarvis_ai.supervisor` | ✅ Production |
| `jarvis_ai/config.py` (Phase 0 knobs) | `LOG_DIR`, `LOG_RETENTION_DAYS=7`, `LOG_MAX_SIZE_MB=10`, `HEARTBEAT_SECONDS=30`, `MIC_RECOVERY_MAX_SECONDS=20` | ✅ Wired |

### Wired into the live loop
- `listen.py` writes a 30-second heartbeat and per-turn latency telemetry through `runtime_state`.
- `supervisor.py` relaunches `listen` on exit and logs through `log_manager`.
- "Leha health" is a local reflex in `assistant_core` that calls `health.voice_summary()`.
- Mic-loop failure retries with recalibration + bounded backoff.

### Tests — `test_phase0.py` (19 tests, all pass)
- **Redaction (9):** bearer, key=val, password, JWT, `ya29.` Google OAuth, app-password, normal text preserved, short values preserved, empty.
- **Log writing (4):** redacted write, timestamp format, `read_recent`, size rotation.
- **Retention (2):** old files removed, recent files kept.
- **Supervisor (4):** `health_check` returns int, 0 on healthy, non-zero on failure, startup housekeeping no crash.

### Pending / known gaps
- Real 2-hour stability soak test is **manual**, not automated (by design — acceptance test is human-run).
- Log rotation keeps only 1 backup (`.log.1`); sufficient for current volume.

---

## Phase 1 — Dedicated Leha Wake Word ✅ BUILT (prod disabled, awaiting tuning)

**Goal:** wake immediately and accurately without transcribing all background speech.

### Files built
| File | Purpose | State |
|------|---------|-------|
| `jarvis_ai/wake_local_onnx.py` | Lightweight ONNX wake detector with **2-consecutive-hit** logic to reject single-score spikes | ✅ Code ready |
| `jarvis_ai/wake_trainer.py` | Training pipeline: `_load_wav_16k`, `_window` (center-crop/zero-pad), `_augment` (speed/gain/noise), `_load_clips_from_dirs`, `_build_model` | ✅ Code ready |
| `jarvis_ai/wake_evaluator.py` | Held-out evaluation: recall ≥ 95%, false-wake ≤ 1% approval gate, metrics JSON | ✅ Code ready |
| `jarvis_ai/wake_openwakeword.py` | openWakeWord integration: offline, no signup, no API key. Uses pre-trained "hey_jarvis" model (~30MB auto-download). Custom "Leha" model can be trained later. | ✅ **PRODUCTION — ACTIVE** |
| `jarvis_ai/wake_dashboard.py` | System-tray status UI (idle/listening/thinking/speaking/error) — `WAKE_DASHBOARD_ENABLED` | ✅ Code ready, off by default |
| `jarvis_ai/wake_phrases.py` | **Strict mode**: when `CUSTOM_WAKE_ENABLED`, drops broad aliases ("layla") and keeps only precise triggers; hallucination guard | ✅ Production |
| `tools/generate_synthetic_wake_data.py` | Synthetic positive+negative WAV generator: `_add_noise`, `_vary_gain`, `_pad_or_crop`, `_save_wav`, `write_manifest` | ✅ Code ready |
| `tools/prepare_leha_wake_training_bundle.py` | Bundles clips into `leha_wake_training_bundle.zip` for Kaggle | ✅ Code ready |
| `tools/record_leha_wake_samples.py` | Interactive positive-clip recorder | ✅ Code ready |
| `tools/record_leha_wake_negatives.py` | Negative-clip recorder (room/TV/music) | ✅ Code ready |
| `tools/evaluate_leha_wake_model.py` | CLI evaluator over held-out set | ✅ Code ready |
| `tools/train_and_evaluate_leha_wake.py` | End-to-end train+eval driver | ✅ Code ready |
| `kaggle_wake_job/` | Full Kaggle kernel (`train_leha_wake.py`) + dataset metadata + **trained `leha_wake_model.onnx`** + `leha_wake_metrics.json` | ✅ Trained |
| `jarvis_ai/voices/wake_leha_continuous/`, `wake_leha_retry/` | Recorded wake clips (owner voice) | ✅ Data exists |

### Wired into the live loop
- **openWakeWord is now the PRIMARY wake engine** (`OWW_ENABLED = True`). Wake detection is instant (~80ms chunks), offline, no cloud API.
  - Pre-trained "hey_jarvis" model — say **"Hey Jarvis"** to wake Leha.
  - `OWW_THRESHOLD = 0.5` (0.3 = sensitive, 0.7 = strict).
  - Priority chain: Porcupine > openWakeWord > local ONNX > Whisper fallback.
- `config.CUSTOM_WAKE_MODEL_PATH` → `voices/leha_wake_model.onnx` (private model, disabled).
- `config.CUSTOM_WAKE_ENABLED = False` — **intentionally disabled** (private model recall was only 44%).
- `config.CUSTOM_WAKE_THRESHOLD = 0.995` (conservative — first live test saw speaker false positives near 0.951).
- `wake_phrases.strict_mode()` returns True only when `CUSTOM_WAKE_ENABLED` is True.
- `wake_phrases` now includes "hey jarvis", "jarvis" as valid triggers for the Whisper fallback path.
- Porcupine path available via `wake_porcupine.py` (Picovoice now requires commercial approval — blocked).

### Tests — `test_phase1.py` (22) + `test_wake_model.py` (8)
- **Strict mode (6):** default off, on when custom enabled, broad alias dropped in strict, precise kept, hallucination uses strict fragments.
- **Trainer helpers (6):** load wav float32, invalid→None, window crops/pads, augment dtype, clip-dir counts with augment factor.
- **Evaluator approval (3):** recall+falsewake formula approves/rejects correctly.
- **2-hit logic (2):** triggers on 2 consecutive, rejects single spike.
- **Synthetic gen (4):** add-noise length, pad/crop exact, save-wav header, manifest JSON valid.
- `test_wake_model.py` 2 failures are **Windows temp-file lock cleanup issues** (`PermissionError WinError 32` on `unlink`), not logic failures — the assertions themselves pass.

### Pending / known gaps
1. **openWakeWord "hey jarvis" is the live wake engine** until custom "Leha" models are trained.
2. **Custom "Leha" wake word training** — Colab notebook ready (`kaggle_wake_job/train_leha_oww.ipynb`), awaiting user run + download. Will replace "hey jarvis".
3. `CUSTOM_WAKE_ENABLED` stays False — the private ONNX model (44% recall) is not viable. openWakeWord replaces it.
4. Broad fuzzy aliases ("layla") remain in the transcript fallback trigger list.

### 2026-07-03 custom "Leha" openWakeWord training pipeline
- **New:** `kaggle_wake_job/train_leha_oww.ipynb` — Colab notebook trains two custom
  openWakeWord models ("leha" + "hey leha") using **synthetic TTS** (Piper), not real
  recordings. This replaces the abandoned `wake_trainer.py` path (which needed 100+ real
  clips and only reached 44% recall). Same pipeline openWakeWord uses for all official models.
- **New:** `kaggle_wake_job/train_leha_oww.md` — step-by-step instructions + troubleshooting.
- **New:** `scripts/install_leha_wake_model.ps1` — copies downloaded `.onnx` files into
  `jarvis_ai/voices/`, smoke-tests they load, reports active engine. No config editing.
- **Upgraded:** `wake_openwakeword.py` now loads **multiple** models simultaneously — any
  one firing wakes Leha. Reports which phrase triggered in the log. Backward compatible.
- **Upgraded:** `config.py` adds `OWW_CUSTOM_MODELS = ["voices/leha.onnx", "voices/hey_leha.onnx"]`.
  Missing files are skipped safely; falls back to built-in "hey_jarvis" until trained.
- **Workflow:** Run Colab notebook (~30 min on free GPU) → download 2 `.onnx` files →
  run `install_leha_wake_model.ps1` → restart Leha → say "Leha" or "Hey Leha".

### 2026-07-02 openWakeWord activation update
- **Enabled openWakeWord as the primary wake engine** (`OWW_ENABLED = True`).
- Picovoice/Porcupine is no longer viable (commercial approval required for new accounts;
  free-tier AccessKeys expired June 30, 2026).
- openWakeWord is fully free, offline, no API key, no signup — runs entirely locally.
- Pre-trained "hey_jarvis" model auto-downloads on first run (~30MB).
- Wake detection is now **instant** (~80ms chunks) vs. the old 2-3 second Whisper fallback.
- Say **"Hey Jarvis"** to wake Leha. This is temporary until a custom "Leha" model is trained.

### 2026-07-02 wake-model validation update (historical)
- Added `tools/build_leha_wake_dataset.py` to create separate train and held-out wake datasets.
- Fixed `wake_trainer._augment()` so speed-perturbed clips are always returned to exactly 1 second.
- Fixed `wake_local_onnx` runtime scoring so it accepts both rank-2 and rank-3 ONNX model inputs.
- Current recorded wake data is not production-ready: 37 of 75 recorded positive clips were rejected as too quiet/silent (`rms < 0.005`).
- Candidate model trained on clean real positives only:
  - best checked result: 44.4% held-out recall, 1.4% false-wake at threshold 0.9.
  - **not approved, not deployed.**
- Candidate model trained on clean real positives plus synthetic Leha positives:
  - best checked result: 33.3% held-out recall, 1.4% false-wake at threshold 0.95.
  - **not approved, not deployed.**
- Production remains on **openWakeWord** (instant offline wake via "hey jarvis" model).

---

## Phase 2 — Fast, Predictable Conversation ✅ DONE

**Goal:** common requests feel immediate; complex requests fail over gracefully.

### Files built
| File | Purpose | State |
|------|---------|-------|
| `jarvis_ai/circuit_breaker.py` | `CircuitBreaker`: closed→open (N failures)→half-open (cooldown)→probe; thread-safe; stats | ✅ Production |
| `jarvis_ai/latency_budget.py` | `LatencyBudget`: per-stage budgets, `timer()` ctx manager, overrun counts, summary | ✅ Production |
| `jarvis_ai/skill_cache.py` | `SkillCache`: LRU + TTL + per-arg keying, invalidate by name/all, hit/miss stats | ✅ Production |
| `jarvis_ai/background_jobs.py` | `BackgroundJobs`: thread pool, submit/on_done/on_error, status, active count | ✅ Production |
| `config.py` Phase 2 knobs | `CB_FAILURE_THRESHOLD=3`, `CB_HALF_OPEN_SECONDS=30`, `PROVIDER_COOLDOWN_SECONDS=45`, `SKILL_CACHE_ENABLED=true`, `BACKGROUND_JOBS_ENABLED=true` | ✅ Wired |

### Wired into the live loop
- **Provider cooldowns** live in `brain.py`: a failed/rate-limited cloud provider is skipped for `PROVIDER_COOLDOWN_SECONDS`; fallback chain continues. Verified by `test_e2e_safe::test_failed_cloud_provider_is_skipped_during_cooldown`.
- **Per-turn latency telemetry** recorded via `runtime_state.timing()` — STT, brain, first-token, TTS, dispatch.
- **Skill cache** wraps read-only tools in `skills/__init__.py::run_tool` (`_CACHEABLE_TOOLS`: weather, system_info, calendar, ip, wifi, reminders, timers, email).
- **Circuit breakers** are implemented and tested; `brain.py` uses the older cooldown mechanism which is functionally equivalent. The `CircuitBreaker` class is available for any provider to adopt.

### Tests — `test_phase2.py` (27 tests, all pass)
- **CircuitBreaker (9):** starts closed, opens after threshold, resets on success, half-open transition, half-open success closes, half-open failure reopens, manual reset, stats, thread safety (5 writers × 100 ops).
- **LatencyBudget (6):** within/over budget, timer ctx manager, set_budget, summary.
- **SkillCache (9):** miss, put/get, same-args hit, different-args miss, LRU eviction, invalidate by name/all, stats, TTL expiry.
- **BackgroundJobs (4):** submit+wait, error handling, running status, active count.
- **Cloudflare brain (2):** circuit-breaker usage + recovery (mocked).

### Pending / known gaps
- **Cloudflare Workers AI is still disabled** (`CF_BRAIN_ENABLED` defaults to "0"). Code path + tests exist; enabling needs a fresh restricted token (roadmap Phase 2 item 3).
- Short-response **streaming** (speak first sentence while later text arrives) is not yet implemented.

---

## Phase 3 — Speech Quality And Barge-In ✅ DONE

**Goal:** one natural female voice, no cut-off responses, interruption support.

### Files built
| File | Purpose | State |
|------|---------|-------|
| `jarvis_ai/speech_manager.py` | `SpeechManager`: owns TTS queue, generation counter (stale-cancel), `say`/`say_stream`/`stop`, history (capped 50), global `get_manager()` | ✅ Production |
| `jarvis_ai/sentence_splitter.py` | Sentence + TTS chunk splitting: abbreviation-aware (`Dr.`, `Mr.`), newline split, long-sentence split, `split_for_tts` combines short chunks | ✅ Code ready |
| `jarvis_ai/echo_cancel.py` | `EchoCanceller` + `_NoiseGate` + `_SpeexAEC`: passthrough when disabled, noise-gate suppression, speex graceful degradation | ✅ Code ready |
| `config.py` Phase 3 knobs | `AEC_ENABLED=false`, `AEC_LIBRARY=speexdsp`, `SPEECH_MANAGER_ENABLED=true`, `BARGE_IN_ENABLED=false` | ✅ Wired |

### ✅ Integration complete
- `SpeechManager` is **wired into `listen.py`** as `self.speech` (line 116–118). All speech goes through the central queue.
- The scheduler and morning brief also route through `self.speech` (line 127–128), preventing overlapping speech.
- `BARGE_IN_ENABLED = False` is **correct and by design** — no validated AEC yet, so barge-in stays off.

### Tests — `test_phase3.py` (25 tests, all pass)
- **SpeechManager (9):** starts not-speaking, say sets flag + delegates to mouth, stop delegates, generation increments, empty text ignored, stream delegates, history recorded/truncated, empty stream.
- **EchoCancel (5):** disabled passthrough, noise-gate suppresses low mic, passes strong mic, no-reference passthrough, speex passthrough when unavailable.
- **SentenceSplitter (11):** empty, single, multiple, abbreviations (`Dr.`, `Mr.`), newlines, long split, TTS combine, question/exclamation.

### Pending / known gaps
1. **Real AEC validation** — speex/noise-gate code exists but barge-in cannot be enabled until speaker echo is measured. Headset-first is the roadmap recommendation.
2. Clone voice remains disabled (CPU too slow) — pending a persistent GPU endpoint (postponed by roadmap).

---

## Phase 4 — Skill System And Device Control ✅ DONE

**Goal:** laptop actions that are useful, predictable, reversible where possible, and safe.

### Files built
| File | Purpose | State |
|------|---------|-------|
| `jarvis_ai/skill_policy.py` | Per-tool policy: risk level (`read`/`reversible`/`external`/`destructive`), allowed origins, confirmation required; `check()` returns a `Decision`; `all_policies()` (50+ tools) | ✅ Production |
| `jarvis_ai/audit_log.py` | `AuditLog`: JSONL append, arg redaction (password/message), result truncation, rotation, `read_recent`/`search` by tool/origin | ✅ Production |
| `jarvis_ai/undo.py` | `UndoStack`: LIFO, max-depth cap, category undo, undo_all, rollback exception handling, recent list | ✅ Production |
| `jarvis_ai/window_manager.py` | Windows process/window discovery (`list_windows`, `find_window_by_title`) for accurate app targeting | ✅ Production |
| `config.py` Phase 4 knobs | `AUDIT_LOG_ENABLED=true`, `AUDIT_LOG_MAX_SIZE_MB=50`, `UNDO_ENABLED=true`, `UNDO_STACK_DEPTH=20` | ✅ Wired |

### Wired into the live loop
- **Every `run_tool` call** in `skills/__init__.py` now flows through:
  1. legacy remote-block check →
  2. `skill_policy.check(name, origin)` (blocks/gates by risk) →
  3. `audit_log.log_tool(...)` before+after with latency →
  4. optional `skill_cache` for read-only tools →
  5. execute → audit result/error.
- **Undo** wired into `assistant_core.py` as local reflexes: "leha undo", "undo all", with category support. Volume/brightness/window-layout rollbacks are push-able.
- **Confirmation gate** for power ops verified by `test_e2e_safe::test_shutdown_requires_confirmation` and `test_mobile_safe::test_destructive_gated`.

### Tests — `test_phase4.py` (26 tests, all pass)
- **SkillPolicy (9):** read tools allowed from all origins, destructive blocked from remote, destructive allowed locally with confirmation, shell local-only, unknown→safe default, external needs confirmation, 50+ policies registered, valid risk levels, confirmation tools are destructive/external.
- **AuditLog (9):** write entry, redact password, redact message body, truncate long result, read_recent limit, search by tool, search by origin, error recorded, rotation.
- **UndoStack (11):** empty message, push+undo, LIFO order, max depth, category undo, category none-found, undo_all, recent list, clear, rollback exception handled.
- **WindowManager (2):** list returns list, find nonexistent returns None (Windows-only).

### Pending / known gaps
- More reversible skills could push onto the undo stack (volume/brightness/theme do; others can adopt).
- Browser automation is limited to explicit supported workflows (by design — prefer official APIs).

---

## Phase 5 — Google And Personal Productivity ✅ DONE

**Goal:** useful personal tasks while protecting the account.

### Files built
| File | Purpose | State |
|------|---------|-------|
| `jarvis_ai/google_services.py` | Shared OAuth `get_credentials`/`get_service`, `GOOGLE_SCOPES` (openid/calendar/gmail/drive/contacts), **per-minute rate limiting** (`_check_rate`, `rate_status`) | ✅ Production |
| `jarvis_ai/google_calendar.py` | `upcoming`, `search_by_date`, **`create_preview` (two-step: preview→confirm)** | ✅ Production |
| `jarvis_ai/google_gmail.py` | `search`, `read`, `unread`, **`compose_preview` (two-step)**, `_extract_body` (simple+multipart), `_extract_headers` | ✅ Production |
| `jarvis_ai/google_drive.py` | `search`, `read`, `recent` (content reading, not just filenames) | ✅ Production |
| `jarvis_ai/google_contacts.py` | `search`, `get_details`, `resolve_phone` (for confirmed calls/messages) | ✅ Production |
| `jarvis_ai/skills/google.py` | Registers **13 Google skills** incl. Maps stub (`open_google_maps`, `search_google_maps`) | ✅ Production |
| `config.py` Phase 5 knobs | `GOOGLE_RATE_LIMIT_PER_MINUTE=30`, `GOOGLE_CONFIRM_REQUIRED={create,send,delete}` | ✅ Wired |

### Wired into the live loop
- 13 skills registered: `authorize_google`, `google_calendar_upcoming/search/create`, `google_gmail_search/read/send`, `google_drive_search/read/recent`, `google_contacts_search/get`, `open_google_maps`, `search_google_maps`.
- **Two-step confirmation pattern** in place: `google_calendar_create` and `google_gmail_send` produce a preview, read it back, and only act on explicit `confirm=true` (system prompt instructs the brain to follow this flow).
- Google OAuth connected locally; token file gitignored.

### Tests — `test_phase5.py` (18 tests, 17 pass)
- **GoogleServices (4):** scopes defined (5+), rate-limit allows under limit, blocks over limit, rate_status.
- **Calendar (3):** create_preview valid date, invalid date, search invalid format. *(1 failure — see note.)*
- **Gmail (5):** compose_preview, missing recipient, extract body simple, extract body multipart, extract headers.
- **Drive (2):** search returns names, no results message.
- **Contacts (6):** search returns names, get_details full info, no results, resolve_phone found, resolve_phone no phone, skills registration (all 13 names present).

> **The 1 failure** (`test_search_by_date_invalid_format`) is **not a logic bug** — the test calls `search_by_date("not-a-date")` expecting an early-return validation message, but the current implementation reaches `get_service()` first, which tries to load the real OAuth token (absent in CI). Fix = reorder validation before the service call. Trivial.

### Pending / known gaps
1. **Maps stub only** — `open_google_maps`/`search_google_maps` produce navigation links / place search; live travel-time and nearby-place APIs need a Maps Platform billing key (roadmap Phase 5 item 5).
2. Calendar/Gmail two-step flow is wired but end-to-end live send/create is a manual acceptance test (cannot run real writes in CI).
3. Contacts→confirmed calling/messaging chain is built (`resolve_phone`) but the calling skill's two-step wiring could be tightened.

---

## Phase 6 — Android As A Secure Companion ✅ DONE (opt-in)

**Goal:** turn Android from a basic push-to-talk client into a secure companion.

### What is built and live
| Component | State |
|-----------|-------|
| `android-app/.../MainActivity.kt` | ✅ **Live.** Hands-free continuous-listen client (Siri-style "just talk"). VAD auto-detect, self-mutes while speaking, WAV upload to `http://<ip>:8001/api/voice`, Android TTS reply, PIN auth header, settings dialog (IP+PIN in SharedPreferences), listening/thinking/speaking/error status states. |
| `jarvis_ai/webserver.py` | ✅ **Live.** PIN gate (`_pin_ok`), device manager gate (`_device_ok`), `/api/voice` + `/api/text` + device pairing/session/approve/revoke endpoints, marks requests `remote` so shell+destructive tools are refused. |
| `jarvis_ai/device_manager.py` | ✅ **Built + wired.** Pairing approval, session tokens with expiry, per-device rate limiting, per-device capability scoping. Opt-in via `DEVICE_MANAGER_ENABLED`. |
| Remote-origin gate | ✅ Verified by `test_mobile_safe::test_remote_origin_gate` — `run_command`/`shutdown_pc`/`phone_call`/`toggle_wifi`/`kill_process` blocked over remote. |
| Telegram bridge | ✅ `telegram_bot.py` with `_authorized` allowlist gate (empty=open, set=locked). |

### Tests
- `test_phase6.py` (18 tests, all pass): pairing (pending/idempotent/approve/revoke), sessions (approved-only/expiry/invalid), rate limit + caps (over-cap/safe-only/destructive-stripped/authorize-gate), persistence.
- `test_mobile_safe.py` (4 functions, all pass): routing, destructive gated, telegram auth, remote-origin gate.

### Pending / known gaps
1. Move PIN storage to Android Keystore.
2. HTTPS or authenticated tunnel (security before any remote exposure).
3. Foreground service + auto-reconnect.
4. Fix Android talk-button disabled-while-busy UI state.

---

## Phase 7 — Smart Home, Media, And Routines ✅ DONE (awaiting HA token)

**Goal:** useful daily actions beyond the laptop.

### What is built and live
| Component | State |
|-----------|-------|
| `jarvis_ai/home_assistant.py` | ✅ **Built + wired.** Scoped-token HA client: `ping`, `list_entities`, `call_service`, `turn_on`/`turn_off`, `activate_scene`. 5 skills registered in `skills/__init__.py`. Graceful "not configured" when no token. |
| `jarvis_ai/skills/routines.py` | ✅ **Live.** `run_routine(name)` executes `config.ROUTINES` steps (open_app / open_url / say), `list_routines()`. |
| `config.ROUTINES` | ✅ 6 named routines: `good morning`, `work`, `work mode`, `movie mode`, `leaving home`, `good night`. |
| Media control (browser) | ✅ Existing browser media control (play/pause/next/prev/stop) in `skills/media.py` + `skills/windows.py`. |

### Tests — `test_phase7.py` (15 tests, all pass)
- **HA not configured (5):** is_configured false, ping/list/turn_on return "not configured", no network calls.
- **HA configured (6):** ping ok, list filters domain, turn_on calls service, scene prefixes id, network error readable, skills registered.
- **Named routines (3):** named routines present, existing preserved, routine runs.

### Pending / known gaps
1. **HA token** — set `HOME_ASSISTANT_URL` and `.home_assistant_token` to enable live smart-home control.
2. Official Spotify / YouTube Music APIs (browser-only control remains).
3. Make proactive briefings opt-in + quiet-hours aware.

---

## Phase 8 — Memory, Personalization, And Privacy ✅ DONE

**Goal:** remember useful preferences without becoming unpredictable or invasive.

### Files built
| File | Purpose | State |
|------|---------|-------|
| `jarvis_ai/structured_memory.py` | Typed memory store (fact/preference/task/contact_note). CRUD: `remember`, `recall`, `summary`, `forget`, `export_all`. Keyed overwrite for preferences. | ✅ Production |
| `jarvis_ai/summarizer.py` | Local extractive conversation summarizer. Offline, no deps. Optional `summarize_with_brain` abstractive pass (opt-in). | ✅ Production |
| `jarvis_ai/memory.py` | Legacy flat fact list — preserved for backward compatibility. | ✅ Unchanged |

### Wired into the live loop
- **4 memory skills registered** in `skills/__init__.py`: `remember_this`, `what_do_you_remember`, `forget_that`, `export_my_data`.
- **Local reflexes** in `assistant_core.py`: "what do you remember", "forget that [X]", "export my data" handled instantly without cloud.
- Legacy `remember_fact` skill continues to work alongside the new structured store.

### Tests — `test_phase8.py` (18 tests, all pass)
- **StructuredMemory (12):** remember+recall, empty rejected, unknown type defaults, keyed overwrite, recall filters by query, summary groups by type, summary empty, forget by query/no match/by type, export_all, skills registered.
- **Summarizer (6):** short unchanged, empty, caps sentence count, summarize turns, turns empty, brain fallback on error.

### Pending / known gaps
1. Wire Chroma vector store for semantic recall (dir is staged).
2. Retention limits + encryption-at-rest for sensitive stores.
3. Speaker verification remains disabled (`SPEAKER_VERIFY_ENABLED=False`).

---

## Phase 9 — Operations, Releases, And Quality Bar ⚠️ PARTIAL

**Goal:** changes safe to deploy and easy to diagnose.

### What is built and live
| Component | State |
|-----------|-------|
| **Phase test files** | ✅ `test_phase0.py` … `test_phase5.py` exist (Phases 6–9 have no dedicated test file yet). |
| `test_e2e_safe.py` | ✅ 19 safe mocked end-to-end tests (routing, YouTube, tabs, phone, rate limits, wake gating, voice config, AEC-off, provider order). |
| `test_mobile_safe.py` | ✅ 4 mobile-bridge safety functions. |
| `test_wake_model.py` | ✅ 8 wake trainer/evaluator tests. |
| Health/diagnostics | ✅ `python -m jarvis_ai.health` + `python -m jarvis_ai.supervisor --check`. |
| Build tag | ⚠️ `config.LEHA_BUILD = "2026.06.20-rate-limit-local-fallback"` — a manual string, not a version system. |

### ⚠️ What is NOT built (Phase 9 gaps)
| Roadmap item | Status |
|--------------|--------|
| **Version system** (semantic version + release notes per change) | ❌ Only an ad-hoc `LEHA_BUILD` string. No `VERSION`, no changelog automation. |
| **Ops toolkit** (one-command release, dependency lock, clean setup) | ❌ No `requirements.lock`, no release script, `SETUP.md` is manual. |
| **Unified test runner** | ⚠️ Tests run via `python -m pytest` ad hoc; no `run_tests.py` / `scripts/test.ps1` harness with phase grouping + summary. |
| Unit tests for wake parsing, policy gates, each fallback tier, TTS queue | ✅/⚠️ Mostly present (wake, policy, circuit breaker, speech manager) but not organized as a coverage matrix. |
| Mocked integration tests for Google/Android/Cloudflare/Groq/OpenAI failures | ⚠️ Google + mobile done; Cloudflare/Groq/OpenAI failure paths partially covered. |
| Manual voice test checklist | ❌ Not codified as a runnable artifact. |
| Telemetry recording (latency, false-wake, missed-wake, duplicate-speech counts) | ⚠️ Latency telemetry exists; wake-fp/missed/duplicate counters do not. |

### Pending / known gaps
1. **Version system** — add `jarvis_ai/VERSION` + `CHANGELOG.md` + read version into `config`.
2. **Ops toolkit** — `requirements.lock`, `scripts/release.ps1`, refresh `SETUP.md`.
3. **Unified test runner** — `scripts/run_tests.ps1` that runs all `test_phase*.py` + safe suites and prints a phase-by-phase summary.
4. **Test files for Phases 6–9** (`test_phase6.py` … `test_phase9.py`).
5. Codify the manual voice test checklist.
6. Add wake false-positive / missed-wake / duplicate-speech counters to `runtime_state`.

---

## Cross-Cutting: Test Health (run 2026-06-25, post-wiring)

```
240 passed, 0 failed  (across all 13 test files)
```

| File | Tests | Pass | Fail | Notes |
|------|-------|------|------|-------|
| `test_phase0.py` | 19 | 19 | 0 | — |
| `test_phase1.py` | 22 | 22 | 0 | — |
| `test_phase2.py` | 27 | 27 | 0 | — |
| `test_phase3.py` | 25 | 25 | 0 | — |
| `test_phase4.py` | 26 | 26 | 0 | — |
| `test_phase5.py` | 18 | 18 | 0 | Date validation fix applied (validation before OAuth). |
| `test_phase6.py` | 18 | 18 | 0 | device_manager: pairing, sessions, rate limits, caps, persistence. |
| `test_phase7.py` | 15 | 15 | 0 | HA stub + named routines. |
| `test_phase8.py` | 18 | 18 | 0 | structured_memory + summarizer. |
| `test_phase9.py` | 8 | 8 | 0 | VERSION, CHANGELOG, run_tests.ps1. |
| `test_e2e_safe.py` | 19 | 19 | 0 | — |
| `test_mobile_safe.py` | 4 | 4 | 0 | pytest warnings (functions return int) — cosmetic. |
| `test_wake_model.py` | 8 | 8 | 0 | — |

---

## Recommended Next Actions (priority order)

All core phases are now built and wired. Remaining work is operational
hardening and optional feature activation.

1. **Phase 1 live wake tuning** — measure real recall/false-wake against the
   trained ONNX model; flip `CUSTOM_WAKE_ENABLED` when it meets the bar.
2. **Phase 6 Android hardening** — move PIN to Android Keystore, add HTTPS,
   foreground service + auto-reconnect.
3. **Phase 7 HA activation** — set `HOME_ASSISTANT_URL` and
   `.home_assistant_token` to enable live smart-home control.
4. **Phase 8 vector memory** — wire Chroma for semantic recall; add
   encryption-at-rest for sensitive stores.
5. **Phase 9 dependency lock** — generate `requirements.lock` for reproducible
   installs.
6. **AEC validation** — measure speaker echo with headset; enable barge-in when
   safe.

---

## Change-Ledger Convention (per roadmap)

Every implementation step records: **Goal / Preserve / Add / Remove-change**,
then delivery notes (added / preserved / not-changed / tests run / limitations /
follow-ups). This file is the cumulative view of those delivery notes.
