from unittest import mock

from jarvis_ai import language


def test_detect_telugu_script_and_voice():
    profile = language.detect_language("లేహా ఇప్పుడు సమయం ఎంత?")

    assert profile.code == "te"
    assert profile.edge_voice == "te-IN-ShrutiNeural"


def test_detect_hindi_keyword_and_voice():
    profile = language.detect_language("reply in Hindi")

    assert profile.code == "hi"
    assert profile.edge_voice == "hi-IN-SwaraNeural"


def test_default_is_indian_english():
    profile = language.detect_language("Leha what time is it")

    assert profile.code == "en-IN"
    assert profile.edge_voice == "en-IN-NeerjaNeural"


def test_detect_romanized_telugu_and_voice():
    profile = language.detect_language("nannu antey nanu antundi")

    assert profile.code == "te"
    assert profile.edge_voice == "te-IN-ShrutiNeural"
    assert language.is_romanized_indian_language("nannu antey nanu antundi")


def test_romanized_telugu_instruction_asks_native_script():
    from jarvis_ai.brain import _final_answer_instruction

    instruction = _final_answer_instruction("nannu antey nanu antundi")

    assert "native Indian script" in instruction
    assert "not romanized English letters" in instruction


def test_nvidia_uses_sarvam_for_indian_language_turn():
    from jarvis_ai.brain import _NvidiaSarvamBrain

    with mock.patch("jarvis_ai.brain._openai_tools", return_value=[]), \
         mock.patch("jarvis_ai.brain.config.NVIDIA_API_KEY", "test"), \
         mock.patch("jarvis_ai.brain.config.NVIDIA_BRAIN_MODEL", "z-ai/glm-5.2"), \
         mock.patch("jarvis_ai.brain.config.NVIDIA_INDIAN_LANGUAGE_MODEL", "sarvamai/sarvam-m"):
        brain = _NvidiaSarvamBrain()

    assert brain._model_for("లేహా ఒక కథ చెప్పు") == "sarvamai/sarvam-m"
    assert brain._model_for("Leha write Python code") == "z-ai/glm-5.2"


def test_direct_sarvam_fallback_only_for_indian_turns():
    from jarvis_ai.brain import Brain

    brain = Brain.__new__(Brain)
    brain._nvidia = object()
    brain._sarvam_ai = object()
    brain._cloudflare = None
    brain._groq = None
    brain._openai = None
    brain._local = object()

    indian_chain = brain._chain("లేహా కథ చెప్పు")
    english_chain = brain._chain("Leha tell me a story")

    assert brain._sarvam_ai in indian_chain
    assert brain._sarvam_ai not in english_chain


def test_nvidia_is_skipped_for_english_when_english_flag_disabled():
    from jarvis_ai.brain import Brain

    brain = Brain.__new__(Brain)
    brain._nvidia = object()
    brain._sarvam_ai = None
    brain._cloudflare = object()
    brain._groq = None
    brain._openai = None
    brain._local = object()

    with mock.patch("jarvis_ai.brain.config.NVIDIA_BRAIN_ENGLISH_ENABLED", False), \
         mock.patch("jarvis_ai.brain.language.is_indian_language", return_value=False):
        english_chain = brain._chain("Leha tell me a joke")

    with mock.patch("jarvis_ai.brain.config.NVIDIA_BRAIN_ENGLISH_ENABLED", False), \
         mock.patch("jarvis_ai.brain.language.is_indian_language", return_value=True):
        indian_chain = brain._chain("indian language turn")

    assert brain._nvidia not in english_chain
    assert brain._nvidia in indian_chain


def test_edge_tts_keeps_unicode_text():
    from jarvis_ai.mouth import Mouth

    mouth = Mouth()
    captured = {}

    async def fake_save():
        captured["called"] = True

    class FakeCommunicate:
        def __init__(self, text, voice, rate=None, pitch=None):
            captured["text"] = text
            captured["voice"] = voice

        async def save(self, path):
            await fake_save()

    with mock.patch("edge_tts.Communicate", FakeCommunicate), \
         mock.patch.object(mouth, "_play_edge_file"):
        mouth._speak_edge("నమస్తే")

    assert captured["text"] == "నమస్తే"
    assert captured["voice"] == "te-IN-ShrutiNeural"
