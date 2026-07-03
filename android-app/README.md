# Leha Android App

Native Android client for Leha. The laptop remains the brain and tool runner;
the phone is the always-on microphone, status UI, and speaker.

## Current Mode

- Foreground service owns the microphone.
- With a Picovoice AccessKey, the service arms Porcupine and waits for a wake word.
- If `app/src/main/assets/leha_android.ppn` exists, the wake word is `Leha`.
- If no custom model is bundled but an AccessKey exists, it falls back to built-in `Jarvis`.
- If no AccessKey is saved, the app does not hotword-listen after boot. Manual `ARM LEHA` still works using VAD-only command capture.
- After wake/manual arm, command capture uses VAD plus an 8 second hard cap so it cannot hang forever.
- Audio is posted to the laptop at `POST /api/voice`.
- Replies are spoken using Android TTS.

## Get Your Free Picovoice Key + Leha Model

1. Go to `https://console.picovoice.ai`.
2. Create/log in to your account.
3. Copy your AccessKey from Account / API Keys.
4. In the Android app, open Settings and paste the AccessKey.
5. Optional but recommended: create a custom wake word named `leha`.
6. Download the Android `.ppn`.
7. Put it here:

```text
android-app/app/src/main/assets/leha_android.ppn
```

Without the custom `.ppn`, the app can only use the built-in `Jarvis` wake model.
Without an AccessKey, hotword mode is disabled and manual `ARM LEHA` remains the
fallback.

## Build

From `D:\jarvis\android-app`:

```powershell
$env:JAVA_HOME="$env:ProgramFiles\Android\Android Studio\jbr"
$env:ANDROID_HOME="$env:LOCALAPPDATA\Android\Sdk"
$env:ANDROID_SDK_ROOT="$env:LOCALAPPDATA\Android\Sdk"
.\gradlew.bat :app:assembleDebug --no-daemon
```

APK output:

```text
android-app/app/build/outputs/apk/debug/app-debug.apk
```

Install to connected phone:

```powershell
adb install -r app\build\outputs\apk\debug\app-debug.apk
```

## First Run With USB

1. Start Leha on the laptop.
2. Forward the phone to the laptop server:

```powershell
adb reverse tcp:8001 tcp:8001
```

3. In app Settings:

```text
Laptop IP: 127.0.0.1
PIN: value from D:\jarvis\.web_pin
Picovoice AccessKey: optional, required for real hotword
Sensitivity: 0.7
```

4. Tap `Test Server`.
5. Tap `ARM LEHA`.

## First Run With Wi-Fi

Use your laptop Wi-Fi IP in Settings, for example:

```text
192.168.31.48
```

Phone and laptop must be on the same Wi-Fi, and Windows firewall must allow
TCP port `8001`.

## Behavior

- `ARMED`: foreground notification visible, Porcupine waits for wake word.
- `AWAKE`: command audio is being captured.
- `THINKING`: laptop is processing.
- `SPEAKING`: phone TTS is speaking.
- Then it returns to `ARMED`.

While `THINKING` or `SPEAKING`, the mic loop pauses to prevent self-triggering.

## Boot

The app registers `BOOT_COMPLETED`. After reboot, it only auto-arms if:

- laptop IP is saved, and
- Picovoice AccessKey is saved.

No AccessKey means no true wake word, so boot autostart is intentionally skipped.
Use `ARM LEHA` manually in that case.

## Project Layout

```text
android-app/
  app/build.gradle.kts
  app/src/main/AndroidManifest.xml
  app/src/main/java/com/leha/app/MainActivity.kt
  app/src/main/java/com/leha/app/LehaForegroundService.kt
  app/src/main/java/com/leha/app/BootReceiver.kt
```
