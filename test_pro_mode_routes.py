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


def test_wake_miss_status_routes_without_llm():
    result, calls = _route("wake miss status")
    assert result.handled
    assert result.action == "wake_miss_status"
    assert calls == []


def test_open_file_explorer_routes_without_llm():
    result, calls = _route("can you open file explorer")
    assert result.handled
    assert result.action == "open"
    assert result.reply == "Opening File Explorer."
    assert calls == [("open_app", {"name": "explorer"})]


def test_press_windows_button_routes_without_llm():
    result, calls = _route("press windows button")
    assert result.handled
    assert result.action == "press_key"
    assert calls == [("press_key", {"key": "win"})]


def test_open_power_point_routes_without_llm():
    result, calls = _route("open power point")
    assert result.handled
    assert result.action == "open"
    assert result.reply == "Opening PowerPoint."
    assert calls == [("open_app", {"name": "powerpnt"})]


def test_start_youtube_opens_site_not_music_search():
    result, calls = _route("start youtube")
    assert result.handled
    assert result.action == "open"
    assert result.reply == "Opening YouTube."
    assert calls == [("open_url", {"url": "https://www.youtube.com"})]


def test_play_youtube_still_plays_when_explicit():
    result, calls = _route("play youtube telugu songs")
    assert result.handled
    assert result.action == "youtube_play"
    assert calls == [("play_youtube", {"query": "telugu songs"})]


def test_capabilities_question_routes_without_llm():
    result, calls = _route("what access do you have on my laptop")
    assert result.handled
    assert result.action == "capabilities"
    assert "apps" in result.reply.lower()
    assert calls == []


def test_unknown_app_open_uses_dynamic_windows_resolution():
    result, calls = _route("open visual studio")
    assert result.handled
    assert result.action == "open_dynamic_app"
    assert result.reply == "Opening visual studio."
    assert calls == [("open_app", {"name": "visual studio"})]


def test_unknown_dot_website_open_uses_dynamic_url():
    result, calls = _route("open example dot com")
    assert result.handled
    assert result.action == "open_dynamic_url"
    assert calls == [("open_url", {"url": "example.com"})]


def test_unknown_app_close_uses_dynamic_close_app():
    result, calls = _route("close visual studio")
    assert result.handled
    assert result.action == "close_dynamic_app"
    assert calls == [("close_app", {"name": "visual studio"})]


def test_spoken_hotkey_routes_dynamically():
    result, calls = _route("press control c")
    assert result.handled
    assert result.action == "press_hotkey"
    assert calls == [("press_hotkey", {"keys": "ctrl+c"})]


def test_web_search_routes_without_llm():
    result, calls = _route("search for best Telugu songs")
    assert result.handled
    assert result.action == "web_search"
    assert calls == [("web_search", {"query": "best telugu songs"})]


def test_telugu_song_request_routes_locally_without_llm():
    result, calls = _route("\u0c24\u0c46\u0c32\u0c41\u0c17\u0c41\u0c32\u0c4b \u0c12\u0c15 \u0c2a\u0c3e\u0c1f \u0c2a\u0c3e\u0c21\u0c41")
    assert result.handled
    assert result.action == "telugu_song"
    assert "\u0c2a\u0c4a\u0c26\u0c4d\u0c26\u0c41" in result.reply
    assert len(result.reply.split()) >= 24
    assert calls == []
