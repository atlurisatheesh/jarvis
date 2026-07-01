"""Tests for robust microphone device resolution.

These tests mock sounddevice, so they never open the real microphone.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from jarvis_ai import audio


class TestAudioDeviceResolution(unittest.TestCase):
    def setUp(self):
        self.devices = [
            {"name": "Speaker", "max_input_channels": 0, "hostapi": 0, "default_samplerate": 48000},
            {"name": "Built-in Microphone", "max_input_channels": 1, "hostapi": 0, "default_samplerate": 48000},
            {"name": "USB Headset Mic", "max_input_channels": 1, "hostapi": 1, "default_samplerate": 16000},
        ]
        self.hostapis = [{"name": "WASAPI"}, {"name": "MME"}]

    def _query_devices(self, index=None):
        if index is None:
            return self.devices
        return self.devices[index]

    def test_valid_integer_device_is_preserved(self):
        with patch.object(audio.sd, "query_devices", side_effect=self._query_devices), \
             patch.object(audio.sd, "query_hostapis", return_value=self.hostapis):
            self.assertEqual(audio.resolve_device(2), 2)

    def test_invalid_integer_falls_back_to_default_input(self):
        with patch.object(audio.sd, "query_devices", side_effect=self._query_devices), \
             patch.object(audio.sd, "query_hostapis", return_value=self.hostapis), \
             patch.object(audio.sd.default, "device", (1, None)):
            self.assertEqual(audio.resolve_device(12), 1)

    def test_invalid_integer_falls_back_to_first_input_without_default(self):
        def bad_default(index=None):
            if index == -1:
                raise RuntimeError("no default")
            return self._query_devices(index)

        with patch.object(audio.sd, "query_devices", side_effect=bad_default), \
             patch.object(audio.sd, "query_hostapis", return_value=self.hostapis), \
             patch.object(audio.sd.default, "device", (-1, None)):
            self.assertEqual(audio.resolve_device(99), 1)

    def test_string_prefers_mme_match(self):
        with patch.object(audio.sd, "query_devices", side_effect=self._query_devices), \
             patch.object(audio.sd, "query_hostapis", return_value=self.hostapis):
            self.assertEqual(audio.resolve_device("headset"), 2)

    def test_none_uses_default_input(self):
        with patch.object(audio.sd, "query_devices", side_effect=self._query_devices), \
             patch.object(audio.sd, "query_hostapis", return_value=self.hostapis), \
             patch.object(audio.sd.default, "device", (1, None)):
            self.assertEqual(audio.resolve_device(None), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
