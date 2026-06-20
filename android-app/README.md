# Leha — Native Android App

A real native phone app (home-screen icon, press-to-talk, native voice out) that
talks to the Leha web server running on your laptop.

> The brain + 81 tools run on the **laptop**. This app is the phone front-end.
> Phone and laptop must be on the **same Wi-Fi** (or use a tunnel for anywhere).

## What it does (v1)

- Real app icon "Leha" on your home screen
- Press-and-hold the orb → record → release → sends to laptop
- Laptop transcribes (Deepgram) + runs the full assistant + replies
- Reply shown on screen **and spoken** by the phone (native Android TTS)
- Settings screen for laptop IP + PIN (saved on device)

Not in v1 (needs more work): "Hey Leha" always-on wake word, background service.

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
