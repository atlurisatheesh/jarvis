from pathlib import Path


ROOT = Path(__file__).resolve().parent
APP = ROOT / "android-app" / "app" / "src" / "main"


def test_android_manifest_has_foreground_service_permissions():
    text = (APP / "AndroidManifest.xml").read_text(encoding="utf-8")
    assert "android.permission.RECORD_AUDIO" in text
    assert "android.permission.FOREGROUND_SERVICE" in text
    assert "android.permission.FOREGROUND_SERVICE_MICROPHONE" in text
    assert "android.permission.POST_NOTIFICATIONS" in text
    assert "android.permission.RECEIVE_BOOT_COMPLETED" in text
    assert 'android:name=".LehaForegroundService"' in text
    assert 'android:foregroundServiceType="microphone"' in text
    assert 'android:name=".BootReceiver"' in text
    assert "android.intent.action.BOOT_COMPLETED" in text


def test_android_has_porcupine_dependency():
    text = (ROOT / "android-app" / "app" / "build.gradle.kts").read_text(encoding="utf-8")
    assert 'implementation("ai.picovoice:porcupine-android:2.1.0")' in text


def test_android_foreground_service_exists():
    text = (APP / "java" / "com" / "leha" / "app" / "LehaForegroundService.kt").read_text(encoding="utf-8")
    assert "class LehaForegroundService : Service()" in text
    assert "startForeground" in text
    assert "NotificationChannel" in text
    assert "START_STICKY" in text
    assert "AudioRecord" in text
    assert "/api/voice" in text
    assert "TextToSpeech" in text
    assert "ACTION_START_LISTEN" in text
    assert "ACTION_STOP_LISTEN" in text
    assert ".addAction" in text
    assert 'addHeader("X-Leha-Client", "android")' in text
    assert "ignored_reason" in text
    assert "Waiting for Leha" in text
    assert "Porcupine.Builder()" in text
    assert "setAccessKey(key)" in text
    assert "leha_android.ppn" in text
    assert "setKeyword(Porcupine.BuiltInKeyword.JARVIS)" in text
    assert "process(frame)" in text
    assert "maxCommandMs = 8000" in text
    assert "VOICE_RECOGNITION" in text


def test_android_activity_has_pro_controls():
    text = (APP / "java" / "com" / "leha" / "app" / "MainActivity.kt").read_text(encoding="utf-8")
    assert "Test Server" in text
    assert "Type Command" in text
    assert "/api/health" in text
    assert "/api/text" in text
    assert "commandService(LehaForegroundService.ACTION_START_LISTEN)" in text
    assert "commandService(LehaForegroundService.ACTION_STOP_LISTEN)" in text
    assert "registerReceiver(serviceReceiver" in text
    assert "ARM LEHA" in text
    assert "access_key" in text
    assert "sensitivity" in text
    assert "Picovoice AccessKey" in text
    assert "FOREGROUND" not in text  # Activity delegates foreground details to service.


def test_boot_receiver_requires_setup_and_access_key():
    text = (APP / "java" / "com" / "leha" / "app" / "BootReceiver.kt").read_text(encoding="utf-8")
    assert "Intent.ACTION_BOOT_COMPLETED" in text
    assert 'prefs.getString("ip", "")' in text
    assert 'prefs.getString("access_key", "")' in text
    assert "ACTION_START_LISTEN" in text
    assert "startForegroundService" in text
