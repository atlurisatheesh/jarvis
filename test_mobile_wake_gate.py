from pathlib import Path


ROOT = Path(__file__).resolve().parent


def test_android_voice_uses_wake_gated_server_route():
    text = (ROOT / "jarvis_ai" / "webserver.py").read_text(encoding="utf-8")
    assert "mobile_voice_session = AssistantSession()" in text
    assert 'X-Leha-Client") or "").lower() != "android"' in text
    assert "_route(heard, explicit=explicit)" in text
    assert "if explicit:" in text
    assert "active_session.activate()" in text
    assert 'return text, "", False, result.ignored_reason' in text
