from unittest import mock

from jarvis_ai import assistant_core, skills


def _route(text: str):
    calls = []

    def fake_run_tool(name, args=None):
        calls.append((name, args or {}))
        return f"[mocked {name}]"

    assistant_core._clear_pending()
    with mock.patch.object(skills, "run_tool", side_effect=fake_run_tool):
        result = assistant_core.handle_local_intent(text)
    return result, calls


def test_youtube_music_routes_without_llm():
    result, calls = _route("play ilayaraja music telugu on youtube")
    assert result.handled
    assert result.action == "youtube_play"
    assert calls == [("play_youtube", {"query": "ilayaraja music telugu"})]


def test_youtube_stop_routes_without_llm():
    result, calls = _route("stop youtube")
    assert result.handled
    assert result.action == "media_pause"
    assert calls == [("media_play_pause", {})]


def test_open_google_maps_routes_without_llm():
    result, calls = _route("open google maps")
    assert result.handled
    assert result.action == "open"
    assert result.reply == "Opening Google Maps."
    assert calls == [("open_url", {"url": "https://www.google.com/maps"})]


def test_opened_google_maps_stt_variant_routes_without_llm():
    result, calls = _route("opened google maps")
    assert result.handled
    assert result.action == "open"
    assert result.reply == "Opening Google Maps."
    assert calls == [("open_url", {"url": "https://www.google.com/maps"})]


def test_where_am_i_routes_to_maps_without_llm():
    result, calls = _route("where am i")
    assert result.handled
    assert result.action == "current_location"
    assert "Opening Google Maps" in result.reply
    assert calls == [("open_url", {"url": "https://www.google.com/maps"})]


def test_mangled_where_am_i_routes_to_maps_without_llm():
    result, calls = _route("let her ver i am i")
    assert result.handled
    assert result.action == "current_location"
    assert "Opening Google Maps" in result.reply
    assert calls == [("open_url", {"url": "https://www.google.com/maps"})]


def test_close_the_youtube_tab_routes_without_llm():
    result, calls = _route("close the youtube tab")
    assert result.handled
    assert result.action == "close_tab"
    assert result.reply == "Closed the current YouTube tab."
    assert calls == [("close_current_tab", {"count": 1})]


def test_close_youtube_tab_can_be_wake_free_after_media():
    from jarvis_ai.assistant_session import AssistantSession

    calls = []

    def fake_run_tool(name, args=None):
        calls.append((name, args or {}))
        return f"[mocked {name}]"

    assistant_core._clear_pending()
    assistant_core.set_media_active("youtube_play")
    session = AssistantSession(followup_seconds=0)
    with mock.patch.object(skills, "run_tool", side_effect=fake_run_tool):
        result = session.handle("close the youtube tab", lambda _: "brain should not run")

    assert result.acted
    assert result.reply == "Closed the current YouTube tab."
    assert calls == [("close_current_tab", {"count": 1})]
    assistant_core.clear_media_active()


def test_close_current_tab_can_be_wake_free_after_media():
    from jarvis_ai.assistant_session import AssistantSession

    calls = []

    def fake_run_tool(name, args=None):
        calls.append((name, args or {}))
        return f"[mocked {name}]"

    assistant_core._clear_pending()
    assistant_core.set_media_active("youtube_play")
    session = AssistantSession(followup_seconds=0)
    with mock.patch.object(skills, "run_tool", side_effect=fake_run_tool):
        result = session.handle("close the current tab", lambda _: "brain should not run")

    assert result.acted
    assert result.reply == "Closed the current YouTube tab."
    assert calls == [("close_current_tab", {"count": 1})]
    assistant_core.clear_media_active()


def test_home_assistant_status_routes_without_llm():
    result, calls = _route("home assistant status")
    assert result.handled
    assert calls == [("home_assistant_ping", {})]


def test_home_assistant_list_lights_routes_without_llm():
    result, calls = _route("list lights")
    assert result.handled
    assert calls == [("home_assistant_list", {"domain": "light"})]


def test_home_assistant_entity_control_routes_without_llm():
    result, calls = _route("turn on light.living room")
    assert result.handled
    assert calls == [("home_assistant_turn_on", {"entity_id": "light.living_room"})]


def test_home_assistant_scene_routes_without_llm():
    result, calls = _route("activate evening scene")
    assert result.handled
    assert calls == [("home_assistant_scene", {"scene_id": "evening"})]
