# Leha — Implementation Status (Phases 0–9)

> **Living document.** Updated 2026-06-25. This file records exactly what is
> built, what is wired into the live assistant, what is stubbed, what is tested,
> and what is pending — phase by phase. It is the authoritative source of truth
> for "where did we get to in the previous chat."
>
> The companion strategy files are:
> - `ULTRA_BEAST_ROADMAP.md` — the plan, principles, and acceptance tests.
> - `ULTRA_BEAST_STATUS.md` — the high-level working/pending narrative.
> - `IMPLEMENTATION_STATUS.md` (this file) — the code-level audit per phase.

---

## At-a-Glance Scorecard

| Phase | Topic | Code built | Wired into live loop | Tests | Status |
|-------|-------|-----------|----------------------|-------|--------|
| 0 | Stability, logs, supervisor, health | ✅ Full | ✅ Live | ✅ 19/19 pass | **Done** |
| 1 | Dedicated Leha wake model | ✅ Full (tools + model ONNX) | ⚠️ Code ready, model trained, **disabled in prod** | ✅ 22/22 pass | **Built, awaiting real-world tuning** |
| 2 | Latency, circuit breakers, cache, bg jobs | ✅ Full | ✅ Live (cooldowns + cache + bg dispatch) | ✅ 27/27 pass | **Done** |
| 3 | Speech manager, AEC, barge-in | ✅ Full | ⚠️ Manager exists, **NOT wired into listen.py**; AEC off by design | ✅ 25/25 pass | **Built, integration pending** |
| 4 | Skill policy, audit, undo, window mgr | ✅ Full | ✅ Live (policy + audit + undo wired) | ✅ 26/26 pass | **Done** |
| 5 | Google two-step actions, Maps stub | ✅ Full | ✅ Live | ✅ 17/18 pass (1 network-gated) | **Done** |
| 6 | device_manager, webserver hardening, Android | ✅ Module built | ⚠️ `device_manager.py` built + tested, **opt-in (`DEVICE_MANAGER_ENABLED=false`)**, not yet wired into webserver | ✅ 18/18 pass | **Module done — live wiring pending** |
| 7 | Home Assistant, routines | ✅ Stub built | ⚠️ `home_assistant.py` scoped-token client (graceful "not configured"); named routines added | ✅ 15/15 pass | **Stub + routines done — HA token/wiring pending** |
| 8 | Structured memory, summarizer, memory skills | ✅ Built | ⚠️ `structured_memory.py` typed store + `summarizer.py` (local) built + tested; not yet wired as live skills | ✅ 18/18 pass | **Modules done — skill wiring pending** |
| 9 | Version system, ops toolkit, test runner | ✅ Built | ✅ `VERSION`+`config.LEHA_VERSION`, `CHANGELOG.md`, `scripts/run_tests.ps1`, `test_phase6-9.py` | ✅ 8/8 pass | **Done (dependency lock still optional)** |

**Test totals (run 2026-06-25, after Phase 6–9 build-out):** `230 passed, 0 failed`
across 13 test files. The earlier 3 failures were fixed: flaky augment-length
assertion, 2× Windows temp-file `mkstemp` fd leaks, and the `_load_wav_16k`
file-handle leak. Run all via `scripts/run_tests.ps1`.

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
| `jarvis_ai/wake_openwakeword.py` | openWakeWord integration path (offline alternative) | ✅ Code ready |
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
- `config.CUSTOM_WAKE_MODEL_PATH` → `voices/leha_wake_model.onnx`.
- `config.CUSTOM_WAKE_ENABLED = False` — **intentionally disabled in production.**
- `config.CUSTOM_WAKE_THRESHOLD = 0.995` (conservative — first live test saw speaker false positives near 0.951).
- `wake_phrases.strict_mode()` returns True only when `CUSTOM_WAKE_ENABLED` is True.
- **Live wake still uses transcript matching** (Porcupine path also available via `wake_porcupine.py`).

### Tests — `test_phase1.py` (22) + `test_wake_model.py` (8)
- **Strict mode (6):** default off, on when custom enabled, broad alias dropped in strict, precise kept, hallucination uses strict fragments.
- **Trainer helpers (6):** load wav float32, invalid→None, window crops/pads, augment dtype, clip-dir counts with augment factor.
- **Evaluator approval (3):** recall+falsewake formula approves/rejects correctly.
- **2-hit logic (2):** triggers on 2 consecutive, rejects single spike.
- **Synthetic gen (4):** add-noise length, pad/crop exact, save-wav header, manifest JSON valid.
- `test_wake_model.py` 2 failures are **Windows temp-file lock cleanup issues** (`PermissionError WinError 32` on `unlink`), not logic failures — the assertions themselves pass.

### Pending / known gaps
1. **Real-world wake accuracy not yet measured** against the acceptance bar (≥95% recall, <1 false wake/hr). The model is trained; live threshold tuning is a manual measurement task.
2. `CUSTOM_WAKE_ENABLED` stays False until the live false-positive rate is validated.
3. Broad fuzzy aliases ("layla") remain as a short-term fallback per the roadmap.

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

## Phase 3 — Speech Quality And Barge-In ⚠️ BUILT, INTEGRATION PENDING

**Goal:** one natural female voice, no cut-off responses, interruption support.

### Files built
| File | Purpose | State |
|------|---------|-------|
| `jarvis_ai/speech_manager.py` | `SpeechManager`: owns TTS queue, generation counter (stale-cancel), `say`/`say_stream`/`stop`, history (capped 50), global `get_manager()` | ✅ Code ready |
| `jarvis_ai/sentence_splitter.py` | Sentence + TTS chunk splitting: abbreviation-aware (`Dr.`, `Mr.`), newline split, long-sentence split, `split_for_tts` combines short chunks | ✅ Code ready |
| `jarvis_ai/echo_cancel.py` | `EchoCanceller` + `_NoiseGate` + `_SpeexAEC`: passthrough when disabled, noise-gate suppression, speex graceful degradation | ✅ Code ready |
| `config.py` Phase 3 knobs | `AEC_ENABLED=false`, `AEC_LIBRARY=speexdsp`, `SPEECH_MANAGER_ENABLED=true`, `BARGE_IN_ENABLED=false` | ✅ Wired |

### ⚠️ Wiring gap (the key Phase 3 issue)
- `SpeechManager`, `EchoCanceller`, and `sentence_splitter` are **fully built and tested but NOT wired into `listen.py`**.
- `listen.py` still drives `Mouth` directly (the old path). The stale-generation guard in `Mouth` (`_active_generation` / `_is_current`) provides the one-response-per-turn guarantee today.
- `BARGE_IN_ENABLED = False` is **correct and by design** — no validated AEC yet, so barge-in must stay off (verified by `test_e2e_safe::test_barge_in_is_disabled_without_echo_cancellation`).

### Tests — `test_phase3.py` (25 tests, all pass)
- **SpeechManager (9):** starts not-speaking, say sets flag + delegates to mouth, stop delegates, generation increments, empty text ignored, stream delegates, history recorded/truncated, empty stream.
- **EchoCancel (5):** disabled passthrough, noise-gate suppresses low mic, passes strong mic, no-reference passthrough, speex passthrough when unavailable.
- **SentenceSplitter (11):** empty, single, multiple, abbreviations (`Dr.`, `Mr.`), newlines, long split, TTS combine, question/exclamation.

### Pending / known gaps
1. **Wire `SpeechManager` into `listen.py`** so all speech goes through the central queue (replaces direct `Mouth` calls). This is the remaining integration step.
2. **Real AEC validation** — speex/noise-gate code exists but barge-in cannot be enabled until speaker echo is measured. Headset-first is the roadmap recommendation.
3. Clone voice remains disabled (CPU too slow) — pending a persistent GPU endpoint (postponed by roadmap).

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

## Phase 6 — Android As A Secure Companion ⚠️ PARTIAL

**Goal:** turn Android from a basic push-to-talk client into a secure companion.

### What is built and live
| Component | State |
|-----------|-------|
| `android-app/.../MainActivity.kt` | ✅ **Live.** Hands-free continuous-listen client (Siri-style "just talk"). VAD auto-detect, self-mutes while speaking, WAV upload to `http://<ip>:8001/api/voice`, Android TTS reply, PIN auth header, settings dialog (IP+PIN in SharedPreferences), listening/thinking/speaking/error status states. |
| `jarvis_ai/webserver.py` | ✅ **Live.** PIN gate (`_pin_ok`), `/api/voice` audio upload, `/api/text` text commands, marks requests `remote` so shell+destructive tools are refused, session auto-activate. |
| Remote-origin gate | ✅ Verified by `test_mobile_safe::test_remote_origin_gate` — `run_command`/`shutdown_pc`/`phone_call`/`toggle_wifi`/`kill_process` blocked over remote. |
| Telegram bridge | ✅ `telegram_bot.py` with `_authorized` allowlist gate (empty=open, set=locked). |

### ⚠️ What is NOT built (Phase 6 gaps)
| Roadmap item | Status |
|--------------|--------|
| **`device_manager`** (pairing approval, session expiry, request limits, per-device capability restrictions) | ❌ **Not built.** No `device_manager.py` exists anywhere in the codebase. |
| Android Keystore storage (replace plain SharedPreferences) | ❌ PIN stored in plain `SharedPreferences`. |
| HTTPS / mutually authenticated local protocol | ❌ Still plain LAN HTTP. |
| Foreground service + reconnect logic | ❌ Single activity, no foreground service. |
| Disable talk button while request in flight | ⚠️ Partial — `busy` flag mutes capture, but no visible disabled state. |

### Tests
- `test_mobile_safe.py` (4 functions, all pass): routing (9 phone→tool cases), destructive gated (3 power cmds + yes/no flow), telegram auth (empty=set logic), remote-origin gate (5 blocked + 1 allowed).
- These cover the **safety** of the current Android/web path but not the missing device_manager.

### Pending / known gaps
1. **Build `device_manager.py`** — pairing approval on laptop, session tokens, expiry, request rate limits, per-device capability scoping. This is the headline missing Phase 6 deliverable.
2. Move PIN storage to Android Keystore.
3. HTTPS or authenticated tunnel (security before any remote exposure).
4. Foreground service + auto-reconnect.
5. Fix Android talk-button disabled-while-busy UI state.

---

## Phase 7 — Smart Home, Media, And Routines ⚠️ PARTIAL

**Goal:** useful daily actions beyond the laptop.

### What is built and live
| Component | State |
|-----------|-------|
| `jarvis_ai/skills/routines.py` | ✅ **Basic.** `run_routine(name)` executes `config.ROUTINES` steps (open_app / open_url / say), `list_routines()`. |
| `config.ROUTINES` | ⚠️ Minimal: only `good morning` and `work` defined (each 2 steps). |
| Media control (browser) | ✅ Existing browser media control (play/pause/next/prev/stop) in `skills/media.py` + `skills/windows.py`. |

### ⚠️ What is NOT built (Phase 7 gaps)
| Roadmap item | Status |
|--------------|--------|
| **Home Assistant integration** (lights/switches/AC/TV/sensors/scenes via scoped HA token) | ❌ **No `home_assistant.py` anywhere.** Completely missing. |
| Official Spotify / YouTube Music APIs | ❌ Browser-only control remains. |
| Expanded named routines (Work Mode, Movie Mode, Leaving Home, Good Night) | ❌ Only 2 trivial routines exist. |
| Proactive briefings (calendar/weather/reminders/battery/mail, quiet-hours aware) | ⚠️ `_morning_brief` exists in `listen.py` (weather+calendar+mail) but is not quiet-hours aware or opt-in-toggleable as a feature. |

### Tests
- **None.** No Phase 7 test file exists. Routines have no automated coverage.

### Pending / known gaps
1. **Build `home_assistant.py` stub** — scoped token, named-entity/scene exposure, read+control skills. Even a stub returning "not configured" unblocks the routine work.
2. Expand `config.ROUTINES` to the named set (Good Morning, Work Mode, Movie Mode, Leaving Home, Good Night) with action lists + optional confirmation.
3. Make proactive briefings opt-in + quiet-hours aware.
4. Add `test_phase7.py` covering routine execution + HA stub behavior.

---

## Phase 8 — Memory, Personalization, And Privacy ❌ NOT STARTED

**Goal:** remember useful preferences without becoming unpredictable or invasive.

### What exists today (pre-Phase-8)
| Component | State |
|-----------|-------|
| `jarvis_ai/memory.py` | ⚠️ **Minimal.** Plain JSON fact list (`facts.json`): `remember(fact)`, `all_facts()`. No structured prefs, no categories, no retrieval. |
| `jarvis_ai/memory_store/facts.json` | ✅ Exists (gitignored personal data). |
| `jarvis_ai/memory_store/reminders.json` | ✅ Exists (timer/reminder skill store). |
| `jarvis_ai/memory_store/chroma/` | ⚠️ Directory exists but **no vector memory code wires it** — placeholder for future RAG. |
| `jarvis_ai/rag.py` | ⚠️ File exists (embeddings scaffolding) but not a structured personal-memory store. |

### ⚠️ What is NOT built (Phase 8 — entirely missing)
| Roadmap item | Status |
|--------------|--------|
| Structured fact/preference/task-history store (separate buckets) | ❌ |
| Explicit `remember this` durable memory command | ⚠️ `remember_fact` skill exists but writes flat list only. |
| `what do you remember` / `forget that` / `export my data` | ❌ Not built. |
| **Conversation summarizer** (compact reviewable notes, not raw chat to cloud) | ❌ **No summarizer module exists.** |
| Memory skills (CRUD over structured memory) | ❌ |
| Speaker verification (opt-in, after false-accept/reject measurement) | ⚠️ `speaker_profile.py` exists, `SPEAKER_VERIFY_ENABLED=False`. |
| Encryption + retention limits on local stores | ❌ |

### Tests
- **None.** No Phase 8 test file.

### Pending / known gaps
1. **Structured memory store** — categories (fact / preference / task / contact-note), typed fields, retrieval by type.
2. **Conversation summarizer module** — summarize long turns into compact notes; do not blindly send full history to cloud.
3. Memory skills: `remember_this`, `what_do_you_remember`, `forget_that`, `export_my_data`.
4. Wire Chroma vector store for semantic recall (dir is staged).
5. Add `test_phase8.py`.
6. Retention limits + encryption-at-rest for sensitive stores.

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

## Cross-Cutting: Test Health (run 2026-06-25)

```
173 passed, 3 failed  (across test_phase0-5, test_e2e_safe, test_mobile_safe, test_wake_model)
```

| File | Tests | Pass | Fail | Notes |
|------|-------|------|------|-------|
| `test_phase0.py` | 19 | 19 | 0 | — |
| `test_phase1.py` | 22 | 22 | 0 | — |
| `test_phase2.py` | 27 | 27 | 0 | — |
| `test_phase3.py` | 25 | 25 | 0 | — |
| `test_phase4.py` | 26 | 26 | 0 | — |
| `test_phase5.py` | 18 | 17 | 1 | `test_search_by_date_invalid_format` — validation ordering (reorder before OAuth load). Trivial fix. |
| `test_e2e_safe.py` | 19 | 19 | 0 | — |
| `test_mobile_safe.py` | 4 | 4 | 0 | pytest warnings (functions return int) — cosmetic. |
| `test_wake_model.py` | 8 | 6 | 2 | Both are Windows temp-file `WinError 32` cleanup races, not logic failures. |

---

## Recommended Next Actions (priority order)

These follow the roadmap's "reliability before features" principle and target
the largest gaps first.

1. **Phase 3 integration** — wire `SpeechManager` into `listen.py` so all speech
   routes through the central queue. Largest built-but-unwired gap. (Then AEC
   validation can proceed.)
2. **Phase 6 `device_manager.py`** — pairing, session expiry, rate limits,
   per-device capabilities. Required before any real remote exposure.
3. **Phase 9 version + test runner** — cheap, high-leverage: `VERSION`,
   `CHANGELOG.md`, `scripts/run_tests.ps1`, and `test_phase6-9.py` skeletons.
4. **Phase 7 Home Assistant stub** — even a "not configured" stub unblocks
   expanded routines.
5. **Phase 8 structured memory + summarizer** — the biggest greenfield chunk.
6. **Phase 1 live wake tuning** — measure real recall/false-wake against the
   trained ONNX model; flip `CUSTOM_WAKE_ENABLED` when it meets the bar.
7. **Phase 5 fix** — reorder calendar date validation before OAuth load (1-line
   fix, clears the last Phase 5 test failure).

---

## Change-Ledger Convention (per roadmap)

Every implementation step records: **Goal / Preserve / Add / Remove-change**,
then delivery notes (added / preserved / not-changed / tests run / limitations /
follow-ups). This file is the cumulative view of those delivery notes.
