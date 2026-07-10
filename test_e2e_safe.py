"""Safe end-to-end checks for Leha.

All external actions are mocked. This test never sends a keypress, changes a
system setting, opens an app, contacts a phone, or executes power commands.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from jarvis_ai import config
from jarvis_ai import assistant_core
from jarvis_ai.assistant_session import AssistantSession
from jarvis_ai.brain import Brain, _GroqRateLimited
from jarvis_ai.ears import Ears
from jarvis_ai.mouth import Mouth
from jarvis_ai.skills import phone


class SafeEndToEndTests(unittest.TestCase):
    def setUp(self):
        assistant_core._clear_pending()
        self.calls: list[tuple[str, dict]] = []

        def fake_tool(name: str, args: dict) -> str:
            self.calls.append((name, dict(args or {})))
            return f"mocked {name}"

        self.tool_patch = patch("jarvis_ai.assistant_core.skills.run_tool", side_effect=fake_tool)
        self.tool_patch.start()
        self.addCleanup(self.tool_patch.stop)
        self.confirmed_tool_patch = patch(
            "jarvis_ai.assistant_core.skills.run_confirmed_tool", side_effect=fake_tool
        )
        self.confirmed_tool_patch.start()
        self.addCleanup(self.confirmed_tool_patch.stop)

    def session(self) -> AssistantSession:
        return AssistantSession(followup_seconds=25)

    def test_youtube_command_reaches_local_tool(self):
        result = self.session().handle("Leha play Ilayaraja Telugu music", lambda _: "brain should not run")
        self.assertTrue(result.acted)
        self.assertEqual(result.reply, "mocked play_youtube")
        self.assertEqual(self.calls[-1], ("play_youtube", {"query": "ilayaraja telugu music"}))

    def test_close_youtube_tab_reaches_tab_tool(self):
        result = self.session().handle("Leha close youtube tab", lambda _: "brain should not run")
        self.assertTrue(result.acted)
        self.assertEqual(self.calls[-1], ("close_current_tab", {"count": 1}))

    def test_phone_status_and_screenshot_routes_are_local(self):
        session = self.session()
        first = session.handle("Leha phone status", lambda _: "brain should not run")
        second = session.handle("take phone screenshot", lambda _: "brain should not run")
        self.assertTrue(first.acted)
        self.assertTrue(second.acted)
        self.assertEqual(self.calls[-2], ("phone_status", {}))
        self.assertEqual(self.calls[-1], ("phone_screenshot", {}))

    def test_open_phone_app_uses_package_alias(self):
        result = self.session().handle("Leha open whatsapp on my phone", lambda _: "brain should not run")
        self.assertTrue(result.acted)
        self.assertEqual(self.calls[-1], ("phone_open_app", {"package": "com.whatsapp"}))

    def test_shutdown_requires_confirmation(self):
        session = self.session()
        prompt = session.handle("Leha shut down laptop", lambda _: "brain should not run")
        self.assertIn("Say yes or no", prompt.reply)
        self.assertFalse(any(name == "shutdown_pc" for name, _ in self.calls))
        confirmed = session.handle("yes", lambda _: "brain should not run")
        self.assertEqual(confirmed.reply, "mocked shutdown_pc")
        self.assertEqual(self.calls[-1], ("shutdown_pc", {}))

    def test_unaddressed_app_command_is_ignored(self):
        result = self.session().handle("open chrome", lambda _: "brain should not run")
        self.assertEqual(result.ignored_reason, "no wake trigger")
        self.assertFalse(self.calls)

    def test_unaddressed_background_speech_cannot_run_tools(self):
        result = self.session().handle("lead generation", lambda _: "brain should not run")
        self.assertEqual(result.ignored_reason, "no wake trigger")
        self.assertFalse(self.calls)

    def test_zero_followup_mode_requires_wake_for_each_turn(self):
        session = AssistantSession(followup_seconds=0)
        session.activate()
        result = session.handle("what time is it", lambda _: "brain should not run")
        self.assertEqual(result.ignored_reason, "no wake trigger")

    def test_bare_wake_accepts_exactly_one_command(self):
        session = AssistantSession()
        first = session.handle("Leha", lambda _: "brain should not run")
        self.assertTrue(first.acted)
        result = session.handle("open chrome", lambda _: "brain should not run")
        self.assertTrue(result.acted)
        self.assertEqual(self.calls[-1], ("open_app", {"name": "chrome"}))
        ignored = session.handle("open PowerPoint", lambda _: "brain should not run")
        self.assertEqual(ignored.ignored_reason, "no wake trigger")

    def test_phone_skill_builds_adb_commands_without_running_adb(self):
        commands: list[tuple[str, ...]] = []
        with patch("jarvis_ai.skills.phone._adb", side_effect=lambda *args, **_: commands.append(args) or "ok"):
            phone.phone_open_app("com.whatsapp")
            phone.phone_send_sms("12345", "hello there")
            phone.phone_key("home")
        self.assertEqual(commands[0][:3], ("shell", "monkey", "-p"))
        self.assertEqual(commands[1][:3], ("shell", "am", "start"))
        self.assertEqual(commands[2], ("shell", "input", "keyevent", "KEYCODE_HOME"))

    def test_voice_configuration_is_loadable(self):
        self.assertIn(
            config.TTS_ENGINE,
            {"edge", "powershell", "hf", "clone", "piper", "pyttsx3", "elevenlabs"},
        )

    def test_health_command_is_local_and_safe(self):
        with patch("jarvis_ai.health.voice_summary", return_value="Health: microphone ready."):
            result = self.session().handle("Leha health", lambda _: "brain should not run")
        self.assertTrue(result.acted)
        self.assertEqual(result.reply, "Health: microphone ready.")
        self.assertFalse(self.calls)

    def test_new_speech_generation_invalidates_stale_audio(self):
        mouth = Mouth()
        generation = mouth._active_generation()
        mouth.stop()
        self.assertFalse(mouth._is_current(generation))

    def test_rate_limit_uses_local_brain_instead_of_spoken_error(self):
        class RateLimitedGroq:
            def ask(self, _text):
                raise _GroqRateLimited("test")

        class LocalFallback:
            def __init__(self):
                self.called = False

            def ask(self, _text):
                self.called = True
                return "slow local reply"

        local = LocalFallback()
        brain = Brain.__new__(Brain)
        brain._groq = RateLimitedGroq()
        brain._local = local
        self.assertEqual(Brain.ask(brain, "hello"), "slow local reply")
        self.assertTrue(local.called)

    def test_failed_cloud_provider_is_skipped_during_cooldown(self):
        class FailedCloud:
            provider_name = "groq"

            def __init__(self):
                self.calls = 0

            def ask(self, _text):
                self.calls += 1
                raise _GroqRateLimited("test")

        class LocalFallback:
            def ask(self, _text):
                return "local reply"

        cloud = FailedCloud()
        brain = Brain.__new__(Brain)
        brain._cloudflare = None
        brain._groq = cloud
        brain._openai = None
        brain._local = LocalFallback()
        brain._cooldowns = {}
        self.assertEqual(Brain.ask(brain, "first"), "local reply")
        self.assertEqual(Brain.ask(brain, "second"), "local reply")
        self.assertEqual(cloud.calls, 1)

    def test_voice_capture_allows_a_natural_pause(self):
        # Voice turns should remain natural but not add nearly half a second of
        # unnecessary latency before cloud transcription begins.
        self.assertGreaterEqual(config.SILENCE_MS, 300)

    def test_barge_in_is_disabled_without_echo_cancellation(self):
        self.assertFalse(config.BARGE_IN_ENABLED)

    def test_auto_ears_prefers_deepgram_then_sarvam_then_openai_then_groq(self):
        with patch.object(config, "DEEPGRAM_API_KEY", "deepgram-key"), \
             patch.object(config, "SARVAM_API_KEY", "sarvam-key"), \
             patch.object(config, "OPENAI_API_KEY", "openai-key"), \
             patch.object(config, "GROQ_API_KEY", "groq-key"):
            self.assertEqual(Ears._select_engine("auto"), "deepgram")
        with patch.object(config, "DEEPGRAM_API_KEY", ""), \
             patch.object(config, "SARVAM_API_KEY", "sarvam-key"), \
             patch.object(config, "OPENAI_API_KEY", "openai-key"), \
             patch.object(config, "GROQ_API_KEY", "groq-key"):
            self.assertEqual(Ears._select_engine("auto"), "sarvam")
        with patch.object(config, "DEEPGRAM_API_KEY", ""), \
             patch.object(config, "SARVAM_API_KEY", ""), \
             patch.object(config, "OPENAI_API_KEY", "openai-key"), \
             patch.object(config, "GROQ_API_KEY", "groq-key"):
            self.assertEqual(Ears._select_engine("auto"), "openai")
        with patch.object(config, "DEEPGRAM_API_KEY", ""), \
             patch.object(config, "SARVAM_API_KEY", ""), \
             patch.object(config, "OPENAI_API_KEY", ""), \
             patch.object(config, "GROQ_API_KEY", "groq-key"):
            self.assertEqual(Ears._select_engine("auto"), "groq")

    def test_cloud_ears_uses_fallback_without_permanently_replacing_primary(self):
        ears = Ears.__new__(Ears)
        ears.engine = "openai"
        ears._disabled_providers = set()
        ears._provider_order = ["openai", "groq"]
        ears.model = None
        with patch.object(ears, "_openai", return_value=""), \
             patch.object(ears, "_groq", return_value="Leha heard this"):
            self.assertEqual(ears.transcribe_file("ignored.wav"), "Leha heard this")
        self.assertEqual(ears.engine, "openai")
        self.assertEqual(ears._provider_order, ["openai", "groq"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
