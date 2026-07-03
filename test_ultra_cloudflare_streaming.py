"""Ultra-mode regression tests for Cloudflare brain activation and streaming."""
from __future__ import annotations

import unittest
from unittest.mock import Mock, patch


class TestCloudflareConfig(unittest.TestCase):
    def test_default_cloudflare_model_is_current_fast_70b(self):
        from jarvis_ai import config
        self.assertEqual(
            config.CF_BRAIN_MODEL,
            "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
        )

    def test_parse_colon_format(self):
        from jarvis_ai import config
        account, token = config._parse_cloudflare_creds("acct123:tok456")
        self.assertEqual(account, "acct123")
        self.assertEqual(token, "tok456")

    def test_parse_labelled_format(self):
        from jarvis_ai import config
        account, token = config._parse_cloudflare_creds(
            "account id: acct123\napikey: tok456\n"
        )
        self.assertEqual(account, "acct123")
        self.assertEqual(token, "tok456")

    def test_parse_env_style_format(self):
        from jarvis_ai import config
        account, token = config._parse_cloudflare_creds(
            "CLOUDFLARE_ACCOUNT_ID=acct123\nCLOUDFLARE_API_TOKEN=tok456\n"
        )
        self.assertEqual(account, "acct123")
        self.assertEqual(token, "tok456")


class TestCloudflareHealth(unittest.TestCase):
    def test_startup_gate_accepts_cloudflare_brain(self):
        from jarvis_ai import health
        status = {
            "mic_configured": "ok",
            "deepgram_key": "ok",
            "openai_key": "missing",
            "groq_key": "missing",
            "cloudflare": "ok",
            "ollama": "down",
        }
        with patch.object(health, "check", return_value=status), \
             patch.object(health, "mic_self_test", return_value={"ok": True}):
            ok, issues = health.startup_gate()
        self.assertTrue(ok)
        self.assertEqual(issues, [])

    def test_health_reports_cloudflare_model(self):
        from jarvis_ai import health
        status = health.check()
        self.assertIn("cloudflare_model", status)

    def test_cloudflare_probe_classifies_429(self):
        from jarvis_ai import health

        response = Mock()
        response.ok = False
        response.status_code = 429
        response.text = "quota exhausted"
        with patch("requests.post", return_value=response):
            result = health.cloudflare_probe()
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "quota_or_rate_limited")


class TestBrainStreaming(unittest.TestCase):
    def test_dispatcher_streams_first_available_streaming_provider(self):
        from jarvis_ai.brain import Brain

        class StreamingProvider:
            provider_name = "cloudflare"

            def __init__(self):
                self.called = False

            def ask_stream(self, text):
                self.called = True
                yield "hello"
                yield " sir"

        provider = StreamingProvider()
        brain = Brain.__new__(Brain)
        brain._cloudflare = provider
        brain._groq = None
        brain._openai = None
        brain._local = None
        brain._breakers = {}
        brain._cooldowns = {}
        brain.last_provider = ""
        brain.last_latency_ms = 0.0

        self.assertEqual("".join(Brain.ask_stream(brain, "hi")), "hello sir")
        self.assertTrue(provider.called)
        self.assertEqual(brain.last_provider, "cloudflare")


if __name__ == "__main__":
    unittest.main(verbosity=2)
