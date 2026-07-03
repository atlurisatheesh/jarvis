from unittest.mock import patch


def test_phone_status_reports_friendly_connected_state():
    from jarvis_ai.skills import phone

    def fake_adb(*args, timeout=20):
        if args == ("devices",):
            return "List of devices attached\nABC123\tdevice\n"
        if args == ("shell", "getprop", "ro.product.model"):
            return "RMX2002"
        if args == ("shell", "getprop", "ro.build.version.release"):
            return "11"
        if args == ("shell", "dumpsys", "battery"):
            return "USB powered: true\nAC powered: false\nlevel: 85\n"
        return ""

    with patch.object(phone, "_adb", side_effect=fake_adb):
        result = phone.phone_status()

    assert result == "Phone connected: RMX2002, Android 11, 85%, charging via USB, USB ADB."


def test_phone_status_reports_no_device():
    from jarvis_ai.skills import phone

    with patch.object(phone, "_adb", return_value="List of devices attached\n\n"):
        result = phone.phone_status()

    assert "No Android phone detected" in result
