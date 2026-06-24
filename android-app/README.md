# Leha — Native Android App

A real native phone app (home-screen icon, press-to-talk, native voice out) that
talks to the Leha web server running on your laptop.

> The brain + 81 tools run on the **laptop**. This app is the phone front-end.
> Phone and laptop must be on the **same Wi-Fi** (or use a tunnel for anywhere).

## What it does (v2 — hands-free)

- Real app icon "Leha" on your home screen
- Tap **START once** → Leha listens continuously ("just talk", Siri-style)
- Auto-detects when you finish speaking (VAD), sends to laptop, speaks reply,
  then listens again. Mutes itself while speaking (no self-trigger).
- Screen stays awake while active
- Laptop transcribes (Deepgram) + runs the full assistant (92 tools) + replies
- Reply shown **and spoken** by the phone (native Android TTS)
- Settings screen for laptop IP + PIN (saved on device)

Better than Siri at: controlling your actual laptop (apps, files, shell, Windows)
AND your Android phone (SMS, calls, apps) — Siri can't touch your PC.

Not yet: "Hey Leha" wake word with screen off (needs a foreground service +
offline wake model; planned). Today you tap START, then it's hands-free.

## Build it (one time — needs a computer)

You need **Android Studio** (free): https://developer.android.com/studio

1. Open Android Studio → **Open** → select this folder: `D:\jarvis\android-app`
2. Let it sync Gradle + download the Android SDK (first time: a few minutes).
   Android Studio creates the Gradle wrapper automatically.
3. Plug your phone in via USB with **USB debugging on** (already enabled).
4. Top toolbar: pick your phone in the device dropdown → click **Run ▶**.
5. The app installs and launches. The **Leha** icon stays on your home screen.

To share/install without the cable later:
- **Build → Build Bundle(s)/APK(s) → Build APK(s)** → find `app-debug.apk` →
  copy to phone → tap to install (allow "install unknown apps").

## First run

1. Start the laptop server (keep it running):
   ```powershell
   cd D:\jarvis
   python -m jarvis_ai.webserver
   ```
   It prints your **laptop IP** and the **PIN**.
2. Open the Leha app → **Settings** → enter that IP + PIN → Save.
3. Hold the orb, say "what time is it", release. Leha answers + speaks.

## Talks to

`POST http://<laptop-ip>:8001/api/voice` with header `X-Leha-Pin: <pin>` and a
multipart `audio` file. Same server + PIN as the web page. Open the firewall once
(admin PowerShell):

```powershell
New-NetFirewallRule -DisplayName "Leha Web 8001" -Direction Inbound -LocalPort 8001 -Protocol TCP -Action Allow -Profile Private
```

## Project layout

```
android-app/
  settings.gradle.kts        project modules
  build.gradle.kts           plugin versions
  app/
    build.gradle.kts         app deps (okhttp)
    src/main/AndroidManifest.xml
    src/main/java/com/leha/app/MainActivity.kt   the whole app (UI in code)
    src/main/res/...         theme + launcher icon
```
