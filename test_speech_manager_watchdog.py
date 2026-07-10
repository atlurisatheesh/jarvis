import time
from unittest import mock

from jarvis_ai.speech_manager import SpeechManager


class StuckMouth:
    def __init__(self):
        self.stopped = False

    def is_speaking(self):
        return True

    def stop(self):
        self.stopped = True


def test_speech_manager_clears_stale_speaking_state():
    mouth = StuckMouth()
    manager = SpeechManager(mouth)
    manager._set_active(1)
    manager._active_started = time.monotonic() - 10

    with mock.patch("jarvis_ai.speech_manager.config.SPEECH_STALE_SECONDS", 1):
        assert manager.is_speaking() is False

    assert mouth.stopped
