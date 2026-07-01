# Leha Ultra Beast Status

## Current Goal

Leha is a personal Windows and Android-connected voice assistant. The laptop is
the brain and tool runner. The Android app and browser client are remote voice
front ends.

## Built And Working

### Core Voice Assistant

- Assistant name and wake phrase: `Leha`.
- Always-on native listener through `python -m jarvis_ai.main`.
- Wake/session flow: wake phrase -> command. Follow-up mode is currently off
  for stability, so normal commands must include `Leha`.
- Fuzzy wake phrase matching for common transcription variations.
- Dynamic microphone noise calibration and voice activity detection.
- Deepgram speech-to-text as the preferred cloud ears provider.
- OpenAI, Groq, and local Whisper fallback options for speech-to-text.
- Local Ollama brain with `qwen2.5:3b` is installed and active.
- Groq rate limits now fall back to local Ollama instead of speaking a
  "brain busy" reply in the current code.
- Fast local intent handling before the LLM for common commands.

### Voice Output

- Current live TTS mode: `edge`.
- Current configured voice: `en-IN-NeerjaNeural`, a female neural voice.
- Clone voice is disabled for live use because CPU synthesis takes about a
  minute and caused delayed responses.
- Previous clone recordings and clone configuration remain local for later GPU
  work; they are not used by the live assistant.
- TTS playback is now in-process, so it does not create orphaned PowerShell
  MediaPlayer processes.
- Clone worker cancellation code exists for future clone mode.
- Barge-in is disabled by default because the laptop does not yet have real
  acoustic echo cancellation.
- Guarded barge-in code exists for later headset/AEC experiments, but it is
  not part of the live production path today.

### Computer Control

- Open applications and web sites.
- Close current tab, close current window, and close named applications.
- YouTube search/play flow and media play/pause/next/previous controls.
- Volume controls.
- Windows information: CPU, RAM, battery, IP address, processes, Wi-Fi.
- Desktop controls: show desktop, minimize windows, snap windows, switch apps.
- Brightness, display off, dark/light mode, wallpaper, battery report, USB eject.
- Screen OCR, screen awareness, clipboard reading, recent file and file-content search.
- Reminders, timers, routines, memory facts, weather, farm-related helpers.

### Android Device Control

- Android ADB phone status checks.
- Open phone apps by package name.
- Phone screenshot, notifications, ring/find phone, home/back keys, typing.
- SMS draft/send flow, WhatsApp draft flow, recent/unread SMS reads, calling.
- Direct voice routes for common phone actions such as phone status,
  phone screenshot, notifications, and opening WhatsApp.

### Google Integration

- Google Maps navigation links and Maps place search.
- Google OAuth Desktop client configured locally.
- Private OAuth token created locally and excluded from Git.
- Verified read-only Google Calendar access.
- Verified read-only Google Drive search access.
- Verified read-only Google Contacts search access.
- Verified OAuth Gmail search access.
- Google credentials and token files are ignored by Git.

### Browser And Android Clients

- Browser/PWA server with microphone upload, text commands, PIN gate, and LAN use.
- Native Android press-and-hold voice client exists.
- Android client records audio, sends it to the laptop, displays the answer,
  and speaks the response using Android TTS.

### Reliability And Test Coverage

- Windows named mutex prevents more than one current Leha listener instance.
- Listener, brain, browser server, and configuration import cleanly.
- `test_e2e_safe.py` has safe mocked coverage for core routing, YouTube, tab
  closing, Android command construction, rate limits, wake gating, and voice
  configuration.
- Current safe suite: 13 tests.
- The project is pushed to GitHub: `https://github.com/atlurisatheesh/jarvis`.

## Important Current Settings

```text
Live voice:       Edge female neural voice
Clone voice:      Disabled for live use
Brain:            Local Ollama qwen2.5:3b
Wake ack speech:  Disabled to avoid delayed clone acknowledgements
Barge-in:         Disabled until echo cancellation exists
Follow-up mode:   Disabled; say Leha for each normal command
Google OAuth:     Connected locally
```

## Still Pending For True Ultra Beast Mode

### Highest Priority: Voice Reliability

1. Dedicated custom `Leha` wake-word model.
   - Current fuzzy transcription wake matching is less reliable than Siri/Alexa.
   - Recommended direction: Picovoice Porcupine custom keyword or a trained
     openWakeWord model.

2. Real acoustic echo cancellation.
   - Needed for interruption/barge-in while Leha is speaking or music is playing.
   - Without it, the microphone can hear speakers and cause false triggers.

3. Production audio state machine.
   - Explicit states: idle, wake detected, listening, thinking, speaking,
     interrupted, error.
   - One central audio queue with telemetry and cancellation tests.

4. GPU cloned voice.
   - A cloned voice cannot be instant on the current CPU.
   - Required options: local NVIDIA GPU, always-warm Hugging Face endpoint,
     or another permanent GPU service.
   - This is intentionally postponed.

### Assistant Intelligence

1. Faster primary cloud brain with quotas/billing chosen for daily use.
2. Conversation memory with summaries, preferences, and retrieval rules.
3. Better context handling for screen, active app, location, and prior tasks.
4. Proactive briefings based on calendar, travel, weather, reminders, battery,
   unread mail, and time of day.
5. Background task queue for long actions with progress updates.

### Google And Productivity

1. Google Calendar event creation with explicit confirmation.
2. Gmail compose/send with recipient and body confirmation.
3. Google Drive content reading, not only filename search.
4. Contact details lookup and confirmed calling/messaging workflows.
5. Google Maps live travel time and nearby-place APIs if a Maps Platform billing
   account/API key is configured.

### Mobile App

1. Fix audio MIME handling between Android M4A uploads and cloud STT providers.
2. Disable the Android talk button while a request is in flight.
3. Encrypt the laptop PIN/token on Android using Android Keystore storage.
4. Replace plain LAN HTTP with HTTPS or a secure authenticated tunnel.
5. Add a foreground service, notification controls, reconnect logic, and health
   status.
6. Add mobile wake word only after battery, echo, and privacy behavior is clear.
7. Add safe Android tests and Gradle wrapper files for reproducible builds.

### Smart Home And Media

1. Home Assistant integration for lights, switches, AC, TV, sensors, and scenes.
2. Official Spotify or YouTube Music integrations instead of browser-only control.
3. Named routines such as Good Morning, Movie Mode, Leaving Home, and Sleep.

### Security Before Remote Use

1. Set a real Telegram allowlist before enabling the Telegram bridge.
2. Restrict or remove arbitrary `run_command` for browser/Telegram-originated
   requests.
3. Add rate limiting and stronger session authentication to the LAN web server.
4. Keep OAuth tokens, API keys, personal recordings, logs, and phone data out
   of Git.
5. Require confirmation for destructive actions, external messages, calls,
   purchases, account actions, and power controls.

### Operations And Testing

1. Windows startup service/task with one instance, automatic restart, and logs.
2. Health endpoint and diagnostic command for microphone, STT, brain, TTS,
   Google OAuth, ADB, and network state.
3. Real end-to-end microphone/speaker test protocol.
4. Tests for duplicate speech, network failures, cloud rate limits, OAuth token
   refresh, Android retries, and remote authorization.
5. Release process: versioning, dependency lock, build instructions, APK build,
   and recovery documentation.

## Recommended Build Order

1. Stabilize laptop voice loop and add a dedicated Leha wake word.
2. Add health monitoring, Windows startup, and real end-to-end audio tests.
3. Finish Google Calendar/Gmail confirmation workflows.
4. Secure and harden Android/PWA connectivity.
5. Add Home Assistant and official media integrations.
6. Add proactive routines and memory improvements.
7. Move cloned voice to a permanent GPU service.

## Commands

```powershell
# Start native Leha
cd D:\jarvis
python -m jarvis_ai.main

# Check basic setup
python setup_check.py

# Run safe tests
python test_e2e_safe.py

# Run Google OAuth again only if the token is removed or revoked
python -m jarvis_ai.google_auth

# Start browser/PWA server
python -m jarvis_ai.webserver
```
