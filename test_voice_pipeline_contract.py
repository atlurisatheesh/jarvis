from unittest import mock
import threading

from jarvis_ai import assistant_core, skills
from jarvis_ai.assistant_session import AssistantSession
from jarvis_ai.brain import Brain
from jarvis_ai.mouth import Mouth


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
    assert "PowerShell" in results[1].reply
    assert "confirmation" in results[1].reply
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


def test_bare_wake_accepts_one_imperfect_dynamic_transcript():
    session = AssistantSession()
    first = session.handle("Leha", lambda text: f"brain:{text}")
    accepted = session.handle("Two 2", lambda text: f"brain:{text}")
    ignored = session.handle("open chrome", lambda text: f"brain:{text}")

    assert first.reply == "Yes, Sir?"
    assert accepted.reply == "brain:two 2"
    assert accepted.ignored_reason == ""
    assert ignored.ignored_reason == "no wake trigger"


def test_bare_wake_then_known_app_routes_locally():
    results, calls, brain_calls = _session_route([
        "Leha",
        "open chrome browser",
    ])

    assert results[0].reply == "Yes, Sir?"
    assert results[1].reply == "Opening Chrome."
    assert calls == [("open_app", {"name": "chrome"})]
    assert brain_calls == []


def test_unknown_app_uses_dynamic_windows_open_without_brain():
    results, calls, brain_calls = _session_route([
        "Leha",
        "open imaginary banana editor",
    ])

    assert results[1].reply == "Opening imaginary banana editor."
    assert results[1].acted
    assert calls == [("open_app", {"name": "imaginary banana editor"})]
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


def test_stream_failure_after_first_token_never_starts_second_provider():
    class PartialProvider:
        def ask_stream(self, _text):
            yield "First answer."
            raise RuntimeError("connection dropped")

    class BackupProvider:
        called = False

        def ask_stream(self, _text):
            self.called = True
            yield "Duplicate answer."

    partial = PartialProvider()
    backup = BackupProvider()
    brain = Brain.__new__(Brain)
    brain._chain = lambda _text="": [partial, backup]
    brain._ready = lambda _provider: True
    brain._success = lambda _provider, _started: None
    brain._failure = lambda _provider, _error: None

    assert "".join(brain.ask_stream("test")) == "First answer."
    assert backup.called is False


def test_tts_stream_consumes_next_chunk_while_first_chunk_is_playing():
    mouth = Mouth()
    mouth.engine_name = "edge"
    first_started = threading.Event()
    release_first = threading.Event()
    second_generated = threading.Event()
    spoken = []

    def fake_edge(text, _generation=None):
        spoken.append(text)
        if len(spoken) == 1:
            first_started.set()
            release_first.wait(2)

    def tokens():
        yield "one two three four five. "
        second_generated.set()
        yield "six seven eight nine ten."

    mouth._speak_edge = fake_edge
    result = []
    worker = threading.Thread(target=lambda: result.append(mouth.say_stream(tokens())))
    worker.start()
    assert first_started.wait(1)
    assert second_generated.wait(1)
    release_first.set()
    worker.join(2)

    assert worker.is_alive() is False
    assert spoken == ["one two three four five.", "six seven eight nine ten."]
    assert result == ["one two three four five. six seven eight nine ten."]


def test_tts_stream_playback_error_does_not_deadlock_producer():
    mouth = Mouth()
    mouth.engine_name = "edge"
    mouth._speak_edge = mock.Mock(side_effect=RuntimeError("speaker unavailable"))
    worker = threading.Thread(
        target=lambda: mouth.say_stream(iter(["one two three four five. "] * 20))
    )
    worker.start()
    worker.join(2)

    assert worker.is_alive() is False


def test_streamed_answer_uses_elevenlabs_not_system_voice():
    mouth = Mouth()
    mouth.engine_name = "elevenlabs"
    mouth._speak_elevenlabs = mock.Mock()
    mouth._speak_powershell = mock.Mock()

    result = mouth.say_stream(iter(["one two three four five."]))

    assert result == "one two three four five."
    mouth._speak_elevenlabs.assert_called_once()
    mouth._speak_powershell.assert_not_called()


def test_elevenlabs_failure_before_audio_falls_back_once(monkeypatch):
    mouth = Mouth()
    mouth.engine_name = "elevenlabs"
    mouth._speak_edge = mock.Mock()
    response = mock.Mock(ok=False, status_code=503)
    monkeypatch.setattr("requests.post", mock.Mock(return_value=response))

    mouth._speak_elevenlabs("hello", mouth._active_generation())

    mouth._speak_edge.assert_called_once()
    response.close.assert_called_once()


def test_elevenlabs_fixed_phrase_uses_local_clone_cache(monkeypatch, tmp_path):
    mouth = Mouth()
    mouth.engine_name = "elevenlabs"
    cached = tmp_path / "yes-sir.wav"
    cached.write_bytes(b"cached")
    mouth._play_elevenlabs_cache = mock.Mock(return_value=True)
    post = mock.Mock()
    monkeypatch.setattr("jarvis_ai.mouth._elevenlabs_cache_path", lambda _text: str(cached))
    monkeypatch.setattr("requests.post", post)
    generation = mouth._active_generation()

    mouth._speak_elevenlabs("Yes, Sir?", generation)

    mouth._play_elevenlabs_cache.assert_called_once_with(str(cached), generation)
    post.assert_not_called()


def test_elevenlabs_midstream_failure_never_switches_voice(monkeypatch):
    mouth = Mouth()
    mouth.engine_name = "elevenlabs"
    mouth._speak_edge = mock.Mock()
    response = mock.Mock(ok=True)
    class Output:
        def start(self):
            pass

        def write(self, _chunk):
            pass

        def stop(self):
            pass

        def close(self):
            pass

    def broken_chunks(chunk_size=None):
        yield b"\x00\x00"
        raise RuntimeError("lost")

    response.iter_content = broken_chunks
    monkeypatch.setattr("requests.post", mock.Mock(return_value=response))
    monkeypatch.setattr("sounddevice.RawOutputStream", mock.Mock(return_value=Output()))

    mouth._speak_elevenlabs("hello", mouth._active_generation())

    mouth._speak_edge.assert_not_called()
    response.close.assert_called_once()
