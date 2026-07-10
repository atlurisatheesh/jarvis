from unittest import mock

import numpy as np

from jarvis_ai import config
from jarvis_ai.ears import Ears
from jarvis_ai.listen import LehaSession
from jarvis_ai.wake_openwakeword import _update_hit_streaks


def test_deepgram_wake_biased_retry_uses_dedicated_path():
    ears = Ears.__new__(Ears)
    ears.engine = "deepgram"
    audio = np.zeros(1600, dtype=np.int16)
    old_key = config.DEEPGRAM_API_KEY
    config.DEEPGRAM_API_KEY = "test-key"
    try:
        with mock.patch("soundfile.write") as write, \
             mock.patch.object(ears, "_deepgram", return_value="Leha") as deepgram:
            result = ears.transcribe_int16_wake_biased(audio)
        assert result == "Leha"
        assert write.called
        assert deepgram.call_args.kwargs["wake_bias"] is True
    finally:
        config.DEEPGRAM_API_KEY = old_key


def test_deepgram_wake_bias_uses_nova3_keyterm_param():
    ears = Ears.__new__(Ears)
    captured = {}
    old_key = config.DEEPGRAM_API_KEY
    config.DEEPGRAM_API_KEY = "test-key"
    try:
        class FakeResponse:
            ok = True

            def json(self):
                return {
                    "results": {
                        "channels": [
                            {"alternatives": [{"transcript": "Leha"}]}
                        ]
                    }
                }

        def fake_post(*args, **kwargs):
            captured.update(kwargs.get("params", {}))
            captured["request_timeout"] = kwargs.get("timeout")
            return FakeResponse()

        with mock.patch("builtins.open", mock.mock_open(read_data=b"wav")), \
             mock.patch("requests.post", side_effect=fake_post):
            assert ears._deepgram("fake.wav", wake_bias=True) == "Leha"

        assert "keyterm" in captured
        assert "keywords" not in captured
        assert captured["request_timeout"] == config.STT_WAKE_REQUEST_TIMEOUT_SECONDS
    finally:
        config.DEEPGRAM_API_KEY = old_key


def test_wake_biased_retry_disabled_for_non_deepgram():
    ears = Ears.__new__(Ears)
    ears.engine = "openai"
    assert ears.transcribe_int16_wake_biased(np.zeros(1600, dtype=np.int16)) == ""


def test_sarvam_can_independently_verify_ambiguous_wake_audio():
    ears = Ears.__new__(Ears)
    audio = np.zeros(1600, dtype=np.int16)
    old_key = config.SARVAM_API_KEY
    config.SARVAM_API_KEY = "test-key"
    try:
        with mock.patch("soundfile.write") as write, \
             mock.patch.object(ears, "_sarvam", return_value="Leha") as sarvam:
            result = ears.transcribe_int16_sarvam(audio)
        assert result == "Leha"
        assert write.called
        sarvam.assert_called_once()
    finally:
        config.SARVAM_API_KEY = old_key


def test_wake_candidates_accept_either_strict_provider_result():
    ears = Ears.__new__(Ears)
    ears.engine = "deepgram"
    audio = np.zeros(1600, dtype=np.int16)
    old_deepgram = config.DEEPGRAM_API_KEY
    old_sarvam = config.SARVAM_API_KEY
    config.DEEPGRAM_API_KEY = "deepgram-test"
    config.SARVAM_API_KEY = "sarvam-test"
    try:
        with mock.patch("soundfile.write"), \
             mock.patch.object(ears, "_deepgram", return_value="Five"), \
             mock.patch.object(ears, "_sarvam", return_value="Leha"):
            assert ears.transcribe_int16_wake_candidates(audio) == "Leha"
    finally:
        config.DEEPGRAM_API_KEY = old_deepgram
        config.SARVAM_API_KEY = old_sarvam


def test_wake_candidates_do_not_convert_two_nontriggers_into_wake():
    ears = Ears.__new__(Ears)
    ears.engine = "deepgram"
    audio = np.zeros(1600, dtype=np.int16)
    old_deepgram = config.DEEPGRAM_API_KEY
    old_sarvam = config.SARVAM_API_KEY
    config.DEEPGRAM_API_KEY = "deepgram-test"
    config.SARVAM_API_KEY = "sarvam-test"
    try:
        with mock.patch("soundfile.write"), \
             mock.patch.object(ears, "_deepgram", return_value="Yeah"), \
             mock.patch.object(ears, "_sarvam", return_value="Okay"):
            assert ears.transcribe_int16_wake_candidates(audio) in {"Yeah", "Okay"}
    finally:
        config.DEEPGRAM_API_KEY = old_deepgram
        config.SARVAM_API_KEY = old_sarvam


def test_command_candidates_prefer_fuller_sarvam_transcript():
    ears = Ears.__new__(Ears)
    audio = np.zeros(1600, dtype=np.int16)
    old_deepgram = config.DEEPGRAM_API_KEY
    old_sarvam = config.SARVAM_API_KEY
    config.DEEPGRAM_API_KEY = "deepgram-test"
    config.SARVAM_API_KEY = "sarvam-test"
    try:
        with mock.patch("soundfile.write"), \
             mock.patch.object(ears, "_deepgram", return_value="Kalam?"), \
             mock.patch.object(
                 ears,
                 "_sarvam",
                 return_value="What do you know about Abdul Kalam?",
             ):
            result = ears.transcribe_int16_command_candidates(audio)
        assert result == "What do you know about Abdul Kalam?"
    finally:
        config.DEEPGRAM_API_KEY = old_deepgram
        config.SARVAM_API_KEY = old_sarvam


def test_idle_wake_probe_skips_slow_indian_rescue():
    ears = Ears.__new__(Ears)
    ears.engine = "deepgram"
    ears._provider_order = ["deepgram"]
    ears._disabled_providers = set()
    ears.model = None

    with mock.patch.object(ears, "_deepgram", return_value="Greek-looking text"), \
         mock.patch.object(ears, "_rescue_indian_speech") as rescue:
        result = ears.transcribe_file("ignored.wav", rescue_indian=False)

    assert result == "Greek-looking text"
    rescue.assert_not_called()


def test_oww_hybrid_fallback_still_requires_transcript_wake_gate():
    audio = np.zeros(6400, dtype=np.int16)

    class FakeListener:
        def stream_utterances(self, **_kwargs):
            yield ("transcript_fallback", audio)

        def close(self):
            pass

    leha = LehaSession.__new__(LehaSession)
    leha._quit = False
    leha._barge_in_enabled = False
    leha.speech = mock.Mock()
    leha.speech.is_speaking.return_value = False
    leha.session = mock.Mock()
    leha.session.is_active.return_value = False
    leha.start_rms = 180
    leha._handle_audio = mock.Mock(return_value=False)

    leha._run_wake_engine(FakeListener(), "oww-test")

    leha._handle_audio.assert_called_once()
    assert leha._handle_audio.call_args.kwargs["force_active"] is False


def test_oww_requires_consecutive_hits_before_waking():
    counts = {"leha": 0}
    assert _update_hit_streaks({"leha": 0.8}, ["leha"], 0.5, counts, 2)[0] is None
    assert _update_hit_streaks({"leha": 0.1}, ["leha"], 0.5, counts, 2)[0] is None
    assert _update_hit_streaks({"leha": 0.7}, ["leha"], 0.5, counts, 2)[0] is None
    fired, score = _update_hit_streaks({"leha": 0.75}, ["leha"], 0.5, counts, 2)
    assert fired == "leha"
    assert score == 0.75


def test_idle_wake_vad_is_stricter_than_command_vad():
    assert config.OWW_IDLE_VAD_START_RMS > config.SILENCE_RMS
