# Leha Ultra Beast Roadmap

## Purpose

This is the working plan for making Leha a dependable personal assistant on
Windows first, then Android. The target is not a demo that can perform many
commands once. The target is an assistant that wakes reliably, understands a
request, responds quickly, performs only authorized actions, and recovers when
one provider fails.

Siri and Alexa feel fast because their wake detector, speech pipeline, cloud
services, audio cancellation, monitoring, and device integrations are separate
production systems. Leha should be built in the same layers, one reliable layer
at a time.

## Current Baseline

### Working now

- Windows always-on listener is supervised and can restart after a crash.
- Assistant name is `Leha`.
- Deepgram is the preferred speech-to-text provider.
- Brain fallback order is prepared as `Cloudflare -> Groq -> OpenAI -> Ollama`.
  Cloudflare is intentionally disabled until a replacement token is installed.
- Edge `en-IN-NeerjaNeural` is the live female neural voice.
- Clone voice code and recordings are retained, but clone synthesis is disabled
  because it is too slow for real-time conversations on the current CPU.
- Local command routing handles common media, Windows, phone, Google, browser,
  reminders, and information commands before calling a language model.
- Google OAuth is connected locally for the configured Google skills.
- Android control routes exist through ADB and the Android client.
- Safe tests cover command routing, power confirmations, remote-origin blocking,
  phone routing, and fallback behavior.

### Deliberate safety settings

- Every normal request must currently include `Leha`; follow-up mode is off.
- Only explicit media controls such as `stop music` and `pause` work without the
  wake phrase.
- Sleep, restart, shutdown, calls, messages, email sending, and other external
  actions require confirmation.
- Barge-in is disabled because there is no validated acoustic echo cancellation.
- Arbitrary actions from browser and remote clients are restricted.

### Known weaknesses

1. Wake recognition still depends on transcript matching, not a dedicated wake
   detector. It can miss `Leha` or mistake similar speech for it.
2. Full question latency still includes speech endpoint detection, cloud STT,
   model response, and neural TTS. A complete answer in 0.5 seconds is not
   realistic on this hardware or over normal internet connections.
3. There is no acoustic echo cancellation, so speaker audio can interfere with
   listening during music or while Leha speaks.
4. The assistant has many skills, but they need stronger capability checks,
   confirmation rules, and consistent responses.
5. Android is a useful remote client, not yet an always-on secure mobile
   assistant.
6. Clone voice needs a persistent GPU service and better recordings before it
   can sound clear and respond promptly.

## The Architecture We Are Building

```text
Microphone
  -> voice activity detection
  -> dedicated Leha wake detector
  -> command capture
  -> speech-to-text
  -> local intent router
  -> cloud brain fallback chain
  -> skill policy and confirmation gate
  -> Windows / Google / Android / smart-home action
  -> one speech queue
  -> speaker
```

Every arrow needs a timeout, a log entry, and a safe fallback. The assistant
must never create two speech outputs for one user request.

## Delivery Principles

1. Reliability before more features. A smaller assistant that always wakes and
   answers is better than 100 unreliable commands.
2. Preserve existing working behavior. Do not remove, replace, disable, or
   overwrite any current feature, credential setup, integration, wake setting,
   Android capability, Google connection, fallback provider, or local data
   unless the owner explicitly asks for that exact change.
3. Preserve the current live voice. The female Edge neural voice remains the
   production voice. Clone voice, a new TTS provider, or any voice experiment
   must be opt-in, must keep the current voice as fallback, and must never
   silently replace it.
4. Local reflexes first. Stop, volume, media, timer, app control, and system
   status should not wait for an LLM.
5. One owner-facing response per turn. Centralize speech output and cancellation.
6. No destructive or external action without explicit confirmation.
7. Cloud services are optional layers. A provider failure should fall through
   quickly rather than freezing the microphone loop.
8. All credentials, personal audio, OAuth files, phone data, and logs remain
   outside Git.

## Change Ledger: How We Work From Now On

Every implementation step must begin with a short change ledger. This keeps
Leha understandable while it grows and prevents accidental loss of working
features.

### Before changing code

State these four items:

| Item | Required statement |
| --- | --- |
| Goal | The exact user problem being solved |
| Preserve | Existing features, voice, integrations, settings, and data that stay unchanged |
| Add | New files, behavior, configuration, tests, or dependencies being introduced |
| Remove/change | Anything being removed, disabled, renamed, or behaviorally changed; requires explicit owner approval |

### While implementing

1. Keep a discovery note for useful ideas, risks, hidden bugs, performance
   limits, and integration opportunities found during the work.
2. Fix a newly discovered bug immediately only when it is directly required for
   the requested feature or creates a safety/reliability risk.
3. For a useful but separate idea, add it to the **Discovery Backlog** below
   rather than silently expanding the feature into unrelated changes.
4. If a new idea clearly improves the same feature without changing existing
   behavior, implement it only with a test and record it under that feature's
   delivery notes.
5. Never replace the current voice, wake path, brain fallback, Google setup,
   Android setup, or existing tool behavior as a side effect of another task.

### After implementing

Record:

- what was added
- what was preserved
- what was intentionally not changed
- tests run and their result
- known limitations
- newly discovered follow-up ideas

## Discovery Backlog

Ideas discovered during work are collected here before they become implementation
tasks. This is a living list, not permission to change the system silently.

| Discovery | Why it matters | When to implement |
| --- | --- | --- |
| Latency dashboard with per-turn STT, brain, and TTS timings | Finds the real source of slow replies instead of guessing | Phase 2 |
| Audio test recorder with opt-in anonymized local clips | Makes wake and STT failures reproducible | Phase 1 |
| Provider circuit breaker dashboard | Shows when Cloudflare, Groq, OpenAI, or Ollama is skipped | Phase 2 |
| Per-device speech ownership | Prevents browser, Android, and laptop from all speaking one reply | Phase 3 / Phase 6 |
| Safe skill simulator | Lets every device command be tested without touching the laptop | Phase 4 |
| Permission dashboard | Shows Google, Android, Telegram, Home Assistant, and model access in one place | Phase 5 / Phase 6 |

## Phase 0: Stabilize The Existing Assistant

### Goal

Make one laptop voice loop run for hours without duplicate voices, random
answers, or needing an open PowerShell window.

### Work

1. Keep `jarvis_ai.supervisor` as the only production launcher.
2. Install a Windows Task Scheduler startup task that launches the supervisor
   at user logon with hidden output redirected to `logs/`.
3. Add a listener heartbeat every 30 seconds with current audio state, selected
   microphone, STT provider, and last successful turn timestamp.
4. Add a `Leha health` local command that reports mic, internet, STT, brain,
   TTS, Google, Android, and listener status in one short reply.
5. Add automatic recovery for a dead microphone callback, stalled STT request,
   failed TTS playback, and crashed listener process.
6. Keep one central speech queue. A new response cancels stale queued speech;
   no direct skill should speak independently.
7. Retain logs for a bounded number of days and redact tokens from all logs.

### Acceptance tests

- Close PowerShell, log out/in, and confirm the listener comes back once.
- Run for two hours with room speech and no accidental replies.
- Force STT, TTS, and brain failures and verify the listener returns to idle.
- Confirm only one `jarvis_ai.listen` process and one audio output queue exist.

## Phase 1: Dedicated Leha Wake Word

### Goal

Wake immediately and accurately without transcribing all background speech.

### Work

1. Choose one wake engine: a custom Porcupine `Leha` keyword is preferred for
   fast production use; a well-trained openWakeWord model is the offline option.
2. Record 100-200 wake clips from the intended owner in quiet, normal, and
   moderately noisy rooms. Include different distances and speaking speeds.
3. Gather at least 10 times more negative clips: conversation, TV, music,
   phone audio, similar words, silence, and other speakers.
4. Train and evaluate on held-out recordings. Do not use training audio as the
   only test set.
5. Set a threshold using false-wake and missed-wake measurements, then store it
   in configuration.
6. Keep transcript matching as a short-term fallback only; remove dangerous
   broad fuzzy aliases after the dedicated model proves reliable.
7. Show audio state through a tray icon or small status UI: idle, listening,
   thinking, speaking, error.

### Acceptance tests

- At least 95% wake detection in 100 intended attempts.
- Fewer than one false wake in 60 minutes of normal room audio.
- Wake response begins in under 500 ms locally, before cloud STT.
- `lead generation`, music, and TV audio do not wake Leha.

## Phase 2: Fast, Predictable Conversation

### Goal

Make common requests feel immediate and complex requests fail over gracefully.

### Work

1. Expand the deterministic local intent router for time, date, battery,
   volume, media, app open/close, tabs, timers, reminders, and device status.
2. Add a measured latency budget for every turn:
   - wake detection: under 0.5 seconds
   - capture endpoint: 0.3-0.8 seconds
   - STT: target under 1.0 second
   - local intent: under 0.1 second
   - first cloud-model token: target under 1.5 seconds
   - first TTS audio: target under 0.5 seconds after text
3. Enable Cloudflare only after creating a fresh restricted Workers AI token.
   Use a fast instruction model as primary, then Groq, OpenAI, and Ollama.
4. Add per-provider circuit breakers: after repeated failures or rate limits,
   skip a provider for a short cooldown rather than retrying it every turn.
5. Add short response streaming. Speak the first complete sentence while later
   text is still arriving, but never start speech for a tool call until the
   action result is known.
6. Split long actions into background jobs with progress and a final answer.
7. Add a local cache for repeated facts such as time, battery, network, and
   recent device status.

### Acceptance tests

- Local commands respond audibly in under 1.5 seconds after speech ends.
- A Cloudflare, Groq, or OpenAI failure switches to the next provider without a
  second spoken error.
- A model rate limit never blocks microphone capture for more than two seconds.
- A long web/search task reports progress and does not freeze later wake events.

## Phase 3: Speech Quality And Barge-In

### Goal

One natural female voice, no cut-off responses, and interruption support.

### Work

1. Keep Edge neural voice as the stable production voice until clone voice can
   meet latency and quality targets.
2. Add speech segmentation: split at safe sentence boundaries, queue segments,
   and make playback cancellation immediate.
3. Implement a single `speech_manager` module that owns TTS generation,
   playback, queueing, cancellation, and telemetry.
4. Add acoustic echo cancellation through a proven audio stack, preferably with
   headset support first. Do not claim barge-in works until speaker echo is
   measured.
5. After AEC works, let `Leha stop` interrupt ongoing speech or music.
6. For clone voice later, use a persistent GPU endpoint or local NVIDIA GPU.
   Train only with explicit permission from the speaker and clean 30-60 minute
   recordings plus transcripts. Test privacy, quality, latency, and fallback.

### Acceptance tests

- One request creates exactly one voice response.
- No response is cut off during a five-minute test conversation.
- `Leha stop` interrupts speech in under one second with AEC enabled.
- Clone voice is used only when it starts within the configured latency budget;
  otherwise Edge neural voice automatically speaks.

## Phase 4: Skill System And Device Control

### Goal

Make laptop actions useful, predictable, reversible where possible, and safe.

### Work

1. Define every skill with metadata: source allowed, risk level, confirmation
   requirement, timeout, expected response, and audit log fields.
2. Separate read-only, reversible, external, and destructive capabilities.
3. Improve application control using Windows process/window discovery instead
   of guessing process names.
4. Add browser automation only for explicit supported workflows. Prefer official
   APIs over screen scraping where possible.
5. Add a clear app/tab target resolver: `close YouTube`, `close this tab`, and
   `close Chrome` must choose different actions and speak what was closed.
6. Build undo where feasible for volume, window layout, theme, and similar local
   settings.
7. Keep power operations behind a two-turn confirmation and never include them
   in any automatic test run.

### Acceptance tests

- Every high-risk skill is blocked until a confirmation phrase is received.
- A browser/Telegram/Android request cannot run unrestricted shell commands.
- Each successful action reports the exact target and outcome once.
- Mocked end-to-end tests cover every dangerous skill category.

## Phase 5: Google And Personal Productivity

### Goal

Support useful personal tasks while protecting the account.

### Work

1. Finish Calendar read, search, and create flows with event previews and
   confirmation before writing.
2. Finish Gmail search, summarization, draft, and send flows. Read recipient,
   subject, and body back before sending.
3. Add Drive result summaries and explicit document-opening permission.
4. Add Contacts lookup, then use confirmed contacts for calls and messages.
5. Add Maps travel time, navigation links, and nearby places only after Maps
   Platform keys, quotas, and billing limits are configured.
6. Add a permission dashboard listing connected services and a command to
   disconnect/revoke each service.

### Acceptance tests

- Leha never sends a message or creates a calendar event without confirmation.
- OAuth refresh works after a reboot.
- A revoked Google token produces a clear repair instruction instead of failure.

## Phase 6: Android As A Secure Companion

### Goal

Turn Android from a basic push-to-talk client into a secure companion.

### Work

1. Make the Android audio upload format and server STT input identical and test
   it on multiple devices.
2. Disable the talk button while a request is in progress; show listening,
   thinking, speaking, and error states.
3. Store pairing secrets with Android Keystore, never plain preferences.
4. Replace raw LAN HTTP with HTTPS, a private tunnel, or a mutually authenticated
   local protocol.
5. Add device pairing approval on the laptop, session expiry, request limits,
   and remote capability restrictions.
6. Add foreground service behavior, reconnect logic, battery controls, and a
   visible disable switch.
7. Add Android wake word only after battery consumption, privacy, false wakes,
   and background microphone rules are fully understood.

### Acceptance tests

- A paired phone can make a request after Wi-Fi reconnect without reinstallation.
- An unpaired device cannot access any tool.
- Remote destructive actions remain confirmation-gated on the laptop.
- Android speech output never overlaps laptop speech for the same turn.

## Phase 7: Smart Home, Media, And Routines

### Goal

Give Leha useful daily actions beyond the laptop.

### Work

1. Use Home Assistant as the smart-home hub rather than writing separate code
   for every bulb, AC, TV, or sensor brand.
2. Add a scoped Home Assistant token and expose only named entities and scenes.
3. Use official Spotify or YouTube Music APIs where available; retain browser
   media control as fallback.
4. Add named routines: Good Morning, Work Mode, Movie Mode, Leaving Home, and
   Good Night. Each routine lists actions and can require confirmation.
5. Add proactive briefings from calendar, weather, reminders, device battery,
   travel time, and unread mail. Make proactive messages opt-in and quiet-hours
   aware.

### Acceptance tests

- Each named routine runs only its approved action list.
- Leha can explain what a routine will do before it runs.
- Proactive notifications honor quiet hours and can be disabled immediately.

## Phase 8: Memory, Personalization, And Privacy

### Goal

Remember useful preferences without becoming unpredictable or invasive.

### Work

1. Store explicit facts, preferences, and task history separately.
2. Require an explicit `remember this` command for durable personal memory.
3. Add a `what do you remember`, `forget that`, and `export my data` command.
4. Summarize long conversations into compact, reviewable notes rather than
   blindly sending all past chat to cloud models.
5. Add optional speaker verification only after measuring false accepts and
   false rejects with consented voices.
6. Encrypt sensitive local stores where practical and set retention limits.

### Acceptance tests

- Leha can correctly list and delete an explicitly stored fact.
- Personal memory is not sent to cloud providers unless needed for the request.
- Speaker verification can be disabled instantly and never blocks emergency
  local controls such as pause/stop.

## Phase 9: Operations, Releases, And Quality Bar

### Goal

Make changes safe to deploy and easy to diagnose.

### Work

1. Add a version number and release notes for each change.
2. Separate development, test, and production configuration files.
3. Add dependency locking and a clean setup script.
4. Add unit tests for wake parsing, policy gates, each fallback tier, and TTS
   queue behavior.
5. Add mocked integration tests for Google, Android, Cloudflare, Groq, OpenAI,
   and failure conditions.
6. Maintain a manual voice test checklist covering quiet room, music playing,
   headset, laptop speakers, poor network, and reboot.
7. Record latency, wake false positives, missed wakes, provider failures, and
   duplicate speech counts. Improve based on measurements, not guesses.

### Production definition

Leha can be called "Ultra Beast" only when it consistently meets these goals:

| Area | Target |
| --- | --- |
| False wake rate | Fewer than 1 per hour of normal room audio |
| Intended wake rate | At least 95% in a representative test set |
| Local command response | First audio within 1.5 s after speech ends |
| Cloud question response | First audio normally within 3 s on healthy internet |
| Duplicate voice responses | Zero in automated and manual test runs |
| Unsafe action execution | Zero without required confirmation |
| Crash recovery | Listener restarts automatically and reports health |
| Credential handling | No tokens, recordings, or OAuth files in Git/logs |

## Recommended Order Of Work

1. Phase 0: stable one-process listener, speech queue, health and recovery.
2. Phase 1: dedicated Leha wake model with real measurements.
3. Phase 2: latency budget, provider circuit breakers, and Cloudflare activation
   after credential rotation.
4. Phase 3: stable speech manager, then AEC and barge-in.
5. Phase 4: policy-driven device controls and complete safe test coverage.
6. Phase 5 and 6: Google productivity and secure Android pairing.
7. Phase 7 and 8: smart home, routines, memory, and personalization.
8. Phase 9: release process, monitoring, and quality gates.

Do not start GPU voice cloning, mobile wake word, or broad smart-home control
until phases 0-3 are reliable. Those features make an unstable voice loop much
harder to debug.

## Immediate Next Sprint

Completed in the current build:

- Stale Edge speech is cancelled with an utterance-generation guard.
- Listener state and a 30-second heartbeat are written to the supervisor log.
- A microphone-loop failure retries with recalibration and bounded backoff.
- `Leha health` gives a spoken readiness summary.
- A per-user Windows startup launcher is installed when Scheduled Tasks are
  unavailable.
- Per-turn latency telemetry now records STT, brain, first-token, TTS generation,
  and overall dispatch timing in the listener log.
- Cloud brain providers enter a short cooldown after a failure or rate limit;
  the fallback chain continues without retrying the known failing provider.

Delivery note for latency telemetry:

- Preserved: current voice, wake flow, provider order, integrations, and skills.
- Added: log-only measurements and temporary provider cooldowns.
- Not changed: no provider was enabled, disabled, replaced, or removed.
- Verified: safe end-to-end tests cover cooldown behavior; no device actions ran.

Next work:

1. Record the positive, negative, and held-out wake-word evaluation sets using
   the new private tools, then train and evaluate the model.
2. Add Cloudflare provider tests using mocked responses; enable it only with a
   new restricted token.
3. Run the manual audio test checklist and fix the highest measured failure
   before adding another feature.
