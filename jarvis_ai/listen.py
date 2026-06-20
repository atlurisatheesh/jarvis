"""Leha always-on listener (Ultra Beat Mode).

Run with:
    python -m jarvis_ai.listen

Wake-word modes (auto-selected):
  Porcupine  — accurate C-library wake word. Needs free key from console.picovoice.ai
               set PORCUPINE_ACCESS_KEY in config.py / env. Falls back to "jarvis"
               keyword unless PORCUPINE_KEYWORD_PATH points to a custom Leha .ppn.
  Whisper    — fallback when Porcupine not configured. Fuzzy substring match in
               Whisper transcripts. Less accurate but zero extra setup.

Features:
- Barge-in: say wake word while Leha speaks to interrupt immediately.
- Dynamic VAD: noise-calibrated start threshold.
- Audio earcons: startup / wake / error beeps.
- Fast local reflexes: media, volume, time, weather, open/close handled without LLM.
"""
import time
try:
    import winsound
except ImportError:
    winsound = None
from datetime import datetime

from . import config
from . import speaker_profile
from . import wake_porcupine
from . import wake_openwakeword
from .assistant_core import set_last_reply
from .assistant_session import AssistantSession
from .audio import calibrate_noise_floor, stream_utterances
from .brain import Brain
from .ears import Ears
from .mouth import Mouth
from .scheduler import Scheduler
from .wake_phrases import has_trigger, is_hallucination, normalize_text


def _morning_brief(mouth):
    from .skills import farm, reminders

    bits = [f"Good morning, Sir. It is {datetime.now():%I:%M %p}."]
    try:
        bits.append(farm.get_weather())
    except Exception:
        pass
    bits.append(reminders.list_reminders())
    mouth.say(" ".join(bits))


def _play_earcon(kind: str):
    if not config.EARCON_ENABLED or winsound is None:
        return
    freq = config.ASSISTANT_EARCON_FREQ
    dur = config.ASSISTANT_EARCON_DUR_MS
    if kind == "wake":
        winsound.Beep(freq, dur)
    elif kind == "ready":
        winsound.Beep(freq - 200, dur)
    elif kind == "error":
        winsound.Beep(freq - 400, dur // 2)
    elif kind == "startup":
        winsound.Beep(freq, dur)
        winsound.Beep(freq + 200, dur)


class LehaSession:
    def __init__(self):
        print(f"Loading {config.ASSISTANT_NAME} (Ultra Beat Mode)...")
        self.ears = Ears()
        self.brain = Brain()
        self.mouth = Mouth()
        self.scheduler = Scheduler(
            # All replies must share the same speech controller. A second Mouth
            # instance can overlap audio with a command response or briefing.
            mouth=self.mouth,
            brief_callback=lambda: _morning_brief(self.mouth),
        )
        self.scheduler.start()
        self.session = AssistantSession()
        self.start_rms = config.SILENCE_RMS + 100
        self.noise_floor = 0.0
        self._quit = False

    def calibrate(self):
        print("[calibrate] measuring noise floor...", flush=True)
        try:
            self.noise_floor = calibrate_noise_floor(seconds=config.VAD_CALIBRATION_SECONDS)
            self.start_rms = max(int(config.SILENCE_RMS), int(self.noise_floor * 3.0))
            print(f"[calibrate] noise={self.noise_floor:.1f} start_rms={self.start_rms}", flush=True)
        except Exception as e:
            print(f"[calibrate] failed: {e}", flush=True)
            self.start_rms = config.SILENCE_RMS

    def _say(self, text: str):
        if not text:
            return
        set_last_reply(text)
        self.mouth.say(text)

    def _handle_audio(self, audio, *, force_active: bool = False) -> bool:
        """Transcribe + handle one utterance. Returns True if quit requested."""
        try:
            text = self.ears.transcribe_int16(audio).strip()
            if not text:
                return False
            print(f"[debug] heard: '{text}'", flush=True)
            low = normalize_text(text)

            # With barge-in enabled, the mic remains available while Leha is
            # speaking. A wake word or an explicit stop cancels speech first.
            if self.mouth.is_speaking() and config.BARGE_IN_ENABLED:
                if has_trigger(text) or low in {"stop", "pause", "cancel", "nevermind"}:
                    print("[barge-in] interrupting TTS...", flush=True)
                    self.mouth.stop()
                    time.sleep(0.12)

            # Speaker enrollment
            if has_trigger(text) and any(
                p in low for p in ("train my voice", "enroll my voice", "learn my voice")
            ):
                self._say(speaker_profile.enroll(audio))
                return False

            # Speaker verification
            if config.SPEAKER_VERIFY_ENABLED and speaker_profile.has_profile() and has_trigger(text):
                ok, score = speaker_profile.verify(audio)
                print(f"[speaker] score={score:.3f} ok={ok}", flush=True)
                if not ok:
                    self._say("Voice not recognized, Sir.")
                    return False

            if force_active:
                self.session.activate()

            # Track whether streaming brain ran (already spoke via say_stream)
            _streamed = [False]
            def _ask_streaming_tracked(t: str) -> str:
                _streamed[0] = True
                return self._ask_streaming(t)

            result = self.session.handle(text, _ask_streaming_tracked)
            if result.ignored_reason:
                print(f"[debug] ignored: {result.ignored_reason}", flush=True)
                return False

            print(f"You: {result.heard}", flush=True)
            if result.reply:
                if _streamed[0]:
                    # say_stream already started TTS — wait for last chunk to finish
                    self.mouth.join(timeout=30)
                else:
                    # local reflex reply — speak it normally
                    self._say(result.reply)
            return result.quit_requested

        except Exception as e:
            print(f"[error] {e}", flush=True)
            _play_earcon("error")
            return False

    def _ask_streaming(self, text: str) -> str:
        """Brain ask via streaming + sentence-level TTS for lowest perceived latency."""
        token_gen = self.brain.ask_stream(text)
        spoken = self.mouth.say_stream(token_gen)
        return spoken  # return full text so session can store it

    # ── Generic wake-engine runner (shared by Porcupine + OWW) ───────

    def _run_wake_engine(self, listener, engine_name: str):
        """Run any wake engine that yields None (wake) / ndarray (audio)."""
        print(f"[wake/{engine_name}] active.", flush=True)
        try:
            for event in listener.stream_utterances(
                should_mute=self.mouth.is_speaking,
                silence_ms=config.SILENCE_MS,
                max_seconds=config.MAX_COMMAND_SECONDS,
                min_samples=6000,
                start_rms=self.start_rms,
            ):
                if self._quit:
                    break
                if event is None:
                    # Wake word detected
                    if self.mouth.is_speaking():
                        print("[barge-in] interrupting TTS...", flush=True)
                        self.mouth.stop()
                        time.sleep(0.15)
                    _play_earcon("wake")
                    self._say("Yes, Sir?")
                    self.mouth.join(timeout=3.0)
                    self.session.activate()
                else:
                    if self._handle_audio(event, force_active=True):
                        self._quit = True
                        break
        except KeyboardInterrupt:
            pass
        finally:
            if hasattr(listener, "close"):
                listener.close()

    # ── Porcupine mode ────────────────────────────────────────────────

    def _run_porcupine(self):
        listener = wake_porcupine.PorcupineListener()
        self._run_wake_engine(listener, "porcupine")

    # ── openwakeword mode ─────────────────────────────────────────────

    def _run_oww(self):
        listener = wake_openwakeword.OWWListener()
        phrase = getattr(config, "OWW_MODEL_NAME", "hey_jarvis").replace("_", " ")
        print(f"[oww] say '{phrase}' to wake Leha", flush=True)
        self._run_wake_engine(listener, "oww")

    # ── Whisper fallback mode ─────────────────────────────────────────

    def _run_whisper_fallback(self):
        """Whisper-substring wake detection (used when Porcupine not configured).

        Every utterance is sent to Whisper; we check if the transcript contains
        'Leha' (or known manglings). Less accurate than Porcupine.
        """
        print(
            f"[wake/whisper] Porcupine not configured — using fuzzy substring matching.\n"
            f"  For reliable wake word, set PORCUPINE_ACCESS_KEY in config.py.\n"
            f"  Free key: https://console.picovoice.ai/",
            flush=True,
        )
        print(f"Mic always open. Say '{config.ASSISTANT_NAME} ...'. Ctrl+C to quit.", flush=True)

        try:
            for audio in stream_utterances(
                should_mute=(lambda: self.mouth.is_speaking() and not config.BARGE_IN_ENABLED),
                barge_in_active=self.mouth.is_speaking if config.BARGE_IN_ENABLED else None,
                start_rms=self.start_rms,
                silence_ms=config.SILENCE_MS,
                max_seconds=config.MAX_COMMAND_SECONDS,
                min_samples=6000,
            ):
                if self._quit:
                    break
                if self._handle_audio(audio):
                    self._quit = True
                    break
        except KeyboardInterrupt:
            pass

    # ── Entry point ───────────────────────────────────────────────────

    def run(self):
        self.calibrate()
        _play_earcon("startup")
        self._say(f"{config.ASSISTANT_NAME} online.")

        if wake_porcupine.is_available():
            print("[wake] engine: Porcupine (high accuracy)", flush=True)
            self._run_porcupine()
        elif wake_openwakeword.is_available():
            print("[wake] engine: openwakeword (offline, no signup)", flush=True)
            self._run_oww()
        else:
            self._run_whisper_fallback()

        print(f"{config.ASSISTANT_NAME} offline.")
        self.mouth.stop()


def main():
    # A second always-on listener hears the same command and speaks a duplicate
    # reply. Use a Windows named mutex so only one Leha process can own the mic.
    mutex = None
    if __import__("os").name == "nt":
        import ctypes

        mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\LehaVoiceAssistant")
        if not mutex or ctypes.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            if mutex:
                ctypes.windll.kernel32.CloseHandle(mutex)
            print("Leha is already running. Use the existing listener instead.", flush=True)
            return
    session = LehaSession()
    try:
        session.run()
    finally:
        if mutex:
            ctypes.windll.kernel32.CloseHandle(mutex)


if __name__ == "__main__":
    main()
