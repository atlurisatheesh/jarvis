from unittest import mock

from jarvis_ai import assistant_core, skills
from jarvis_ai.assistant_session import AssistantSession


def _session_route(text: str, *, followup_seconds: int = 0):
    calls = []

    def fake_run_tool(name, args=None):
        calls.append((name, args or {}))
        return f"[mocked {name}]"

    assistant_core._clear_pending()
    session = AssistantSession(followup_seconds=followup_seconds)
    with mock.patch.object(skills, "run_tool", side_effect=fake_run_tool):
        result = session.handle(text, lambda _: "brain should not run")
    return result, calls


def test_wake_open_file_explorer_uses_local_tool():
    result, calls = _session_route("Leha open file explorer")
    assert result.acted
    assert result.reply == "Opening File Explorer."
    assert calls == [("open_app", {"name": "explorer"})]


def test_wake_press_windows_button_uses_key_tool():
    result, calls = _session_route("Leha press windows button")
    assert result.acted
    assert result.reply == "[mocked press_key]"
    assert calls == [("press_key", {"key": "win"})]


def test_wake_open_powerpoint_uses_local_tool():
    result, calls = _session_route("Leha open PowerPoint")
    assert result.acted
    assert result.reply == "Opening PowerPoint."
    assert calls == [("open_app", {"name": "powerpnt"})]


def test_wake_current_time_uses_local_tool():
    result, calls = _session_route("Leha tell me the current time in one short sentence")
    assert result.acted
    assert result.reply == "[mocked tell_time]"
    assert calls == [("tell_time", {})]


def test_wake_start_youtube_does_not_play_music():
    result, calls = _session_route("Leha start YouTube")
    assert result.acted
    assert result.reply == "Opening YouTube."
    assert calls == [("open_url", {"url": "https://www.youtube.com"})]


def test_unwoken_random_youtube_words_do_not_open_youtube():
    result, calls = _session_route("youtube music is playing in background")
    assert not result.acted
    assert result.ignored_reason == "no wake trigger"
    assert calls == []


def test_wake_unknown_open_is_dynamic_not_brain():
    result, calls = _session_route("Leha open visual studio")
    assert result.acted
    assert result.reply == "Opening visual studio."
    assert calls == [("open_app", {"name": "visual studio"})]


def test_wake_spoken_hotkey_is_dynamic_not_brain():
    result, calls = _session_route("Leha press control shift escape")
    assert result.acted
    assert result.reply == "[mocked press_hotkey]"
    assert calls == [("press_hotkey", {"keys": "ctrl+shift+esc"})]


def test_telugu_wake_then_song_routes_locally():
    result, calls = _session_route(
        "\u0c32\u0c47\u0c39\u0c3e \u0c24\u0c46\u0c32\u0c41\u0c17\u0c41\u0c32\u0c4b \u0c12\u0c15 \u0c2a\u0c3e\u0c1f \u0c2a\u0c3e\u0c21\u0c41"
    )
    assert result.acted
    assert "\u0c2a\u0c4a\u0c26\u0c4d\u0c26\u0c41" in result.reply
    assert calls == []
