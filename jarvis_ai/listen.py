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
import threading
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
from . import wake_local_onnx
from .assistant_core import set_last_reply
from .assistant_session import AssistantSession
from .audio import calibrate_noise_floor, stream_utterances
from .brain import Brain
from .ears import Ears
from .mouth import Mouth
from .runtime_state import runtime
from .scheduler import Scheduler
from .wake_phrases import has_trigger, is_hallucination, normalize_text

# Phase 2/3 modules: lazily wired when their config flags are enabled.
try:
    from . import latency_budget
except Exception:
    latency_budget = None  # type: ignore[assignment]
try:
    from . import speech_manager
except Exception:
    speech_manager = None  # type: ignore[assignment]
try:
    from .barge_in_guard import BargeInGuard
except Exception:
    BargeInGuard = None  # type: ignore[assignment]


def _morning_brief(mouth):
    from . import skills

    bits = [f"Good morning, Sir. It is {datetime.now():%I:%M %p}."]
    # weather
    try:
        bits.append(skills.run_tool("get_weather", {}))
    except Exception:
        pass
    # today's calendar (Google, if connected)
    try:
        cal = skills.run_tool("google_calendar_upcoming", {"days": 1})
        if cal and "No upcoming" not in cal and "not connected" not in cal.lower():
            bits.append(cal)
    except Exception:
        pass
    # unread email count (Google OAuth, if connected)
    try:
        mail = skills.run_tool("google_gmail_search", {"query": "is:unread", "limit": 3})
        if mail and "No matching" not in mail:
            bits.append("Unread " + mail)
    except Exception:
        pass
    # battery / system
    try:
        bits.append(skills.run_tool("system_info", {}))
    except Exception:
        pass
    # reminders
    try:
        bits.append(skills.run_tool("list_reminders", {}))
    except Exception:
        pass
    mouth.say(" ".join(b for b in bits if b))


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
        print(
            f"Loading {config.ASSISTANT_NAME} (Ultra Beat Mode, "
            f"build {config.LEHA_BUILD})..."
        )
        self.ears = Ears()
        self.brain = Brain()
        self.mouth = Mouth()
        # Phase 3: central speech queue wraps the Mouth TTS generator when
        # enabled. Falls back to raw Mouth when disabled or unavailable.
        self.speech = (speech_manager.get_manager(self.mouth)
                       if config.SPEECH_MANAGER_ENABLED and speech_manager is not None
                       else self.mouth)
        # Phase 2: shared latency budget for per-stage overrun tracking.
        self._budget = (latency_budget.get_latency_budget()
                        if latency_budget is not None else None)
        # Phase A: self-protecting barge-in. Tracks echo self-triggers so a
        # laptop-mic+speaker echo loop disables barge-in for the session.
        self._barge_guard = BargeInGuard() if BargeInGuard is not None else None
        # Effective barge-in state for this session. Copied from config so the
        # guard can disable it without mutating the global config.
        self._barge_in_enabled = bool(config.BARGE_IN_ENABLED)
        self.scheduler = Scheduler(
            # All replies must share the same speech controller. Routing the
            # scheduler and morning brief through self.speech (the central
            # SpeechManager when enabled) instead of the raw Mouth prevents a
            # reminder/briefing from overlapping a command response.
            mouth=self.speech,
            brief_callback=lambda: _morning_brief(self.speech),
        )
        self.scheduler.start()
        self.session = AssistantSession()
        self.start_rms = config.SILENCE_RMS + 100
        self.noise_floor = 0.0
        self._quit = False
        self._heartbeat_stop = threading.Event()

    def calibrate(self):
        runtime.set("calibrating")
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
        runtime.set("speaking")
        if self._barge_guard is not None:
            self._barge_guard.record_spoken(text)
        self.speech.say(text)

    def _heartbeat_loop(self):
        while not self._heartbeat_stop.wait(config.HEARTBEAT_SECONDS):
            snapshot = runtime.snapshot()
            state = "speaking" if self.speech.is_speaking() else snapshot["state"]
            print(
                f"[heartbeat] state={state} turns={snapshot['turns']} "
                f"age={snapshot['age_seconds']}s",
                flush=True,
            )

    def _should_barge_in(self, interrupt_text: str) -> bool:
        """Decide if a wake/stop during speech is a genuine interrupt.

        Returns False (ignore the interrupt, keep speaking) when:
          * barge-in is disabled for this session, or
          * the interrupt looks like Leha's echoed own voice (echo self-trigger).

        When an echo self-trigger trips the guard's threshold, barge-in is
        disabled for the rest of the session.
        """
        if not self._barge_in_enabled:
            return False
        if self._barge_guard is None:
            return True
        disabled_now = self._barge_guard.register_interrupt(interrupt_text)
        if disabled_now:
            self._barge_in_enabled = False
            print(
                "[barge-in] echo self-trigger detected — disabling barge-in "
                "for this session (use a headset/USB mic to keep it on).",
                flush=True,
            )
            return False
        if self._barge_guard.disabled:
            return False
        return True

    def _handle_audio(self, audio, *, force_active: bool = False) -> bool:
        """Transcribe + handle one utterance. Returns True if quit requested."""
        turn_started = time.perf_counter()
        runtime.begin_turn()
        try:
            runtime.set("transcribing")
            stt_started = time.perf_counter()
            text = self.ears.transcribe_int16(audio).strip()
            stt_elapsed = (time.perf_counter() - stt_started) * 1000
            runtime.timing("stt", stt_elapsed)
            if self._budget:
                try:
                    self._budget.record("stt", stt_elapsed / 1000)
                except Exception:
                    pass
            if not text:
                runtime.set("idle")
                return False
            print(f"[debug] heard: '{text}'", flush=True)
            low = normalize_text(text)

            # With barge-in explicitly enabled, the mic remains available while
            # Leha is speaking. Route every interruption through the guard so
            # echoed TTS cannot create a self-trigger loop.
            if self.speech.is_speaking() and self._barge_in_enabled:
                if has_trigger(text) or low in {"stop", "pause", "cancel", "nevermind"}:
                    if self._should_barge_in(text):
                        print("[barge-in] interrupting TTS...", flush=True)
                        self.speech.stop()
                        time.sleep(0.12)
                    else:
                        runtime.set("speaking")
                        return False

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
                runtime.set("idle")
                return False

            print(f"You: {result.heard}", flush=True)
            if result.reply:
                if _streamed[0]:
                    # say_stream already started TTS — wait for last chunk to finish
                    self.speech.join(timeout=30)
                else:
                    # local reflex reply — speak it normally
                    runtime.provider("local_reflex")
                    self._say(result.reply)
            runtime.turn_completed()
            dispatch_elapsed = (time.perf_counter() - turn_started) * 1000
            runtime.timing("turn_dispatch", dispatch_elapsed)
            if self._budget:
                try:
                    self._budget.record("turn_dispatch", dispatch_elapsed / 1000)
                except Exception:
                    pass
            print(runtime.latency_line(), flush=True)
            if not self.speech.is_speaking():
                runtime.set("idle")
            return result.quit_requested

        except Exception as e:
            print(f"[error] {e}", flush=True)
            runtime.error(str(e)[:160])
            _play_earcon("error")
            return False

    def _ask_streaming(self, text: str) -> str:
        """Brain ask via streaming + sentence-level TTS for lowest perceived latency."""
        runtime.set("thinking")
        token_gen = self.brain.ask_stream(text)
        runtime.set("speaking")
        # Route through self.speech (SpeechManager) so generation tracking
        # stays consistent and is_speaking() reflects reality.
        spoken = self.speech.say_stream(token_gen)
        return spoken  # return full text so session can store it

    # ── Generic wake-engine runner (shared by Porcupine + OWW) ───────

    def _run_wake_engine(self, listener, engine_name: str):
        """Run any wake engine that yields None (wake) / ndarray (audio)."""
        print(f"[wake/{engine_name}] active.", flush=True)
        try:
            for event in listener.stream_utterances(
                should_mute=(lambda: self.speech.is_speaking() and not self._barge_in_enabled),
                barge_in_active=(self.speech.is_speaking if self._barge_in_enabled else None),
                silence_ms=config.SILENCE_MS,
                max_seconds=config.MAX_COMMAND_SECONDS,
                min_samples=6000,
                start_rms=self.start_rms,
            ):
                if self._quit:
                    break
                if event is None:
                    # Wake word detected
                    if self.speech.is_speaking():
                        if self._should_barge_in(config.ASSISTANT_NAME):
                            print("[barge-in] interrupting TTS...", flush=True)
                            self.speech.stop()
                            time.sleep(0.15)
                        else:
                            continue
                    _play_earcon("wake")
                    if config.SPEAK_WAKE_ACK:
                        self._say("Ready.")
                        self.speech.join(timeout=3.0)
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
                should_mute=(lambda: self.speech.is_speaking() and not self._barge_in_enabled),
                barge_in_active=self.speech.is_speaking if self._barge_in_enabled else None,
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
        heartbeat = threading.Thread(target=self._heartbeat_loop, daemon=True)
        heartbeat.start()
        recovery_attempts = 0
        try:
            self.calibrate()
            _play_earcon("startup")
            self._say(f"{config.ASSISTANT_NAME} online.")

            while not self._quit:
                try:
                    runtime.set("idle")
                    if wake_porcupine.is_available():
                        print("[wake] engine: Porcupine (high accuracy)", flush=True)
                        self._run_porcupine()
                    elif wake_local_onnx.is_available():
                        print("[wake] engine: private local Leha model", flush=True)
                        self._run_wake_engine(wake_local_onnx.LocalOnnxWakeListener(), "local")
                    elif wake_openwakeword.is_available():
                        print("[wake] engine: openwakeword (offline, no signup)", flush=True)
                        self._run_oww()
                    else:
                        self._run_whisper_fallback()
                    if not self._quit:
                        raise RuntimeError("microphone loop ended unexpectedly")
                except KeyboardInterrupt:
                    self._quit = True
                except Exception as exc:
                    recovery_attempts += 1
                    delay = min(config.MIC_RECOVERY_MAX_SECONDS, 2 ** min(recovery_attempts, 4))
                    runtime.error(f"microphone recovery: {exc}")
                    print(f"[audio] loop failed: {exc}; retrying in {delay}s", flush=True)
                    time.sleep(delay)
                    self.calibrate()
        finally:
            self._heartbeat_stop.set()
            runtime.set("offline")
            print(f"{config.ASSISTANT_NAME} offline.")
            self.speech.stop()


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
