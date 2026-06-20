"""Safe end-to-end checks for Leha.

All external actions are mocked. This test never sends a keypress, changes a
system setting, opens an app, contacts a phone, or executes power commands.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from jarvis_ai import config
from jarvis_ai import assistant_core
from jarvis_ai.assistant_session import AssistantSession
from jarvis_ai.brain import Brain, _GroqRateLimited
from jarvis_ai.ears import Ears
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
        self.assertEqual(config.TTS_ENGINE, "clone")
        self.assertTrue(config.CLONE_TTS_STRICT)
        self.assertTrue(Path(config.CLONE_TTS_REFERENCE).exists())

    def test_rate_limit_does_not_call_slow_local_fallback(self):
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
        self.assertEqual(Brain.ask(brain, "hello"), config.GROQ_RATE_LIMIT_REPLY)
        self.assertFalse(local.called)

    def test_voice_capture_allows_a_natural_pause(self):
        self.assertGreaterEqual(config.SILENCE_MS, 600)

    def test_auto_ears_prefers_deepgram_then_openai_then_groq(self):
        with patch.object(config, "DEEPGRAM_API_KEY", "deepgram-key"), \
             patch.object(config, "OPENAI_API_KEY", "openai-key"), \
             patch.object(config, "GROQ_API_KEY", "groq-key"):
            self.assertEqual(Ears._select_engine("auto"), "deepgram")
        with patch.object(config, "DEEPGRAM_API_KEY", ""), \
             patch.object(config, "OPENAI_API_KEY", "openai-key"), \
             patch.object(config, "GROQ_API_KEY", "groq-key"):
            self.assertEqual(Ears._select_engine("auto"), "openai")
        with patch.object(config, "DEEPGRAM_API_KEY", ""), \
             patch.object(config, "OPENAI_API_KEY", ""), \
             patch.object(config, "GROQ_API_KEY", "groq-key"):
            self.assertEqual(Ears._select_engine("auto"), "groq")

    def test_cloud_ears_switches_to_next_provider_without_local_block(self):
        ears = Ears.__new__(Ears)
        ears.engine = "openai"
        ears._disabled_providers = set()
        ears._provider_order = ["openai", "groq"]
        ears.model = None
        with patch.object(ears, "_openai", return_value=""), \
             patch.object(ears, "_groq", return_value="Leha heard this"):
            self.assertEqual(ears.transcribe_file("ignored.wav"), "Leha heard this")
        self.assertEqual(ears.engine, "groq")


if __name__ == "__main__":
    unittest.main(verbosity=2)
