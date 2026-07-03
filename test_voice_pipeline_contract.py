from unittest import mock

from jarvis_ai import assistant_core, skills
from jarvis_ai.assistant_session import AssistantSession


def _session_route(utterances):
    calls = []
    brain_calls = []
    session = AssistantSession()

    def fake_run_tool(name, args=None):
        calls.append((name, args or {}))
        return f"[mocked {name}]"

    def fake_brain(text):
        brain_calls.append(text)
        return f"brain:{text}"

    assistant_core._clear_pending()
    with mock.patch.object(skills, "run_tool", side_effect=fake_run_tool):
        results = [session.handle(text, fake_brain) for text in utterances]
    return results, calls, brain_calls


def test_no_wake_no_normal_answer_or_tool_action():
    results, calls, brain_calls = _session_route([
        "what access do you have on my laptop",
        "open chrome browser",
        "what time is it",
    ])

    assert [r.ignored_reason for r in results] == [
        "no wake trigger",
        "no wake trigger",
        "no wake trigger",
    ]
    assert calls == []
    assert brain_calls == []


def test_bare_wake_then_dynamic_question_uses_brain_once():
    results, calls, brain_calls = _session_route([
        "Leha",
        "what access do you have on my laptop",
    ])

    assert results[0].reply == "Yes, Sir?"
    assert "control approved apps" in results[1].reply
    assert calls == []
    assert brain_calls == []


def test_bare_wake_then_unknown_question_uses_brain_once():
    results, calls, brain_calls = _session_route([
        "Leha",
        "why is the sky blue",
    ])

    assert results[0].reply == "Yes, Sir?"
    assert results[1].reply == "brain:why is the sky blue"
    assert calls == []
    assert brain_calls == ["why is the sky blue"]


def test_bare_wake_then_known_app_routes_locally():
    results, calls, brain_calls = _session_route([
        "Leha",
        "open chrome browser",
    ])

    assert results[0].reply == "Yes, Sir?"
    assert results[1].reply == "Opening Chrome."
    assert calls == [("open_app", {"name": "chrome"})]
    assert brain_calls == []


def test_unknown_app_does_not_claim_success_or_go_to_brain():
    results, calls, brain_calls = _session_route([
        "Leha",
        "open imaginary banana editor",
    ])

    assert results[1].reply == "I don't know the app imaginary banana editor yet, Sir."
    assert results[1].acted
    assert calls == []
    assert brain_calls == []


def test_wake_free_media_stop_is_still_allowed():
    results, calls, brain_calls = _session_route(["stop music"])

    assert results[0].acted
    assert results[0].reply == "Paused, Sir."
    assert calls == [("media_play_pause", {})]
    assert brain_calls == []


def test_open_google_maps_speaks_app_name_not_url():
    results, calls, brain_calls = _session_route([
        "Leha",
        "open google maps",
    ])

    assert results[1].reply == "Opening Google Maps."
    assert calls == [("open_url", {"url": "https://www.google.com/maps"})]
    assert brain_calls == []


def test_where_am_i_opens_maps_with_clear_instruction():
    results, calls, brain_calls = _session_route([
        "Leha",
        "where am I",
    ])

    assert results[1].reply == "Opening Google Maps. Use the location button there to show exactly where you are."
    assert calls == [("open_url", {"url": "https://www.google.com/maps"})]
    assert brain_calls == []


def test_close_youtube_tab_does_not_open_youtube():
    results, calls, brain_calls = _session_route([
        "Leha",
        "close youtube tab",
    ])

    assert results[1].reply == "Closed the current YouTube tab."
    assert calls == [("close_current_tab", {"count": 1})]
    assert brain_calls == []
