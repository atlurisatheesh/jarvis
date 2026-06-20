"""Text-to-speech with interrupt support."""
import asyncio
import os
import tempfile
import subprocess
import threading
import time
import sys
import numpy as np
from . import config


class Mouth:
    def __init__(self):
        self._lock = threading.Lock()
        self._proc = None
        self._stop_event = threading.Event()
        self._speak_thread = None
        self.engine_name = config.TTS_ENGINE
        if self.engine_name == "piper":
            self._init_piper()
        elif self.engine_name == "clone":
            self.engine = None
        elif self.engine_name == "hf":
            self.engine = None
        elif self.engine_name == "edge":
            self.engine = None
        elif self.engine_name == "powershell":
            self.engine = None
        else:
            self._init_pyttsx3()

    def _init_pyttsx3(self):
        import pyttsx3
        self.engine = pyttsx3.init()
        self.engine.setProperty("rate", config.TTS_RATE)
        self.engine_name = "pyttsx3"

    def _init_piper(self):
        try:
            from piper.voice import PiperVoice
            self.voice = PiperVoice.load(config.PIPER_VOICE)
        except Exception as e:
            print(f"[mouth] Piper unavailable ({e}); using pyttsx3")
            self._init_pyttsx3()

    def stop(self):
        """Interrupt any ongoing speech immediately."""
        with self._lock:
            self._stop_event.set()
            if self._proc:
                try:
                    self._proc.kill()
                except Exception:
                    pass
                self._proc = None
            if self.engine_name == "pyttsx3":
                try:
                    self.engine.stop()
                except Exception:
                    pass

    def is_speaking(self) -> bool:
        return self._speak_thread is not None and self._speak_thread.is_alive()

    def join(self, timeout: float = 30.0):
        if self._speak_thread:
            self._speak_thread.join(timeout=timeout)

    def _speak_powershell(self, text: str):
        safe_text = text.encode("ascii", "ignore").decode("ascii")
        escaped = safe_text.replace("'", "''")
        voice = getattr(config, "POWERSHELL_TTS_VOICE", "").replace("'", "''")
        ps = (
            f"Add-Type -AssemblyName System.Speech; "
            f"$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            f"$preferred = '{voice}'; "
            f"$installed = $s.GetInstalledVoices(); "
            f"$match = $installed | Where-Object {{ $_.VoiceInfo.Name -eq $preferred }} | Select-Object -First 1; "
            f"if (-not $match) {{ $match = $installed | Where-Object {{ $_.VoiceInfo.Gender -eq [System.Speech.Synthesis.VoiceGender]::Female }} | Select-Object -First 1 }}; "
            f"if ($match) {{ $s.SelectVoice($match.VoiceInfo.Name) }}; "
            f"$s.Speak('{escaped}')"
        )
        with self._lock:
            self._stop_event.clear()
            self._proc = subprocess.Popen(
                ["powershell", "-Command", ps],
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        try:
            self._proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self._proc.kill()
        finally:
            with self._lock:
                self._proc = None

    def _play_media_file(self, media_path: str, seconds: float):
        escaped = media_path.replace("'", "''")
        ps = (
            "Add-Type -AssemblyName PresentationCore; "
            "$p = New-Object System.Windows.Media.MediaPlayer; "
            f"$p.Open([Uri]'{escaped}'); "
            "$p.Play(); "
            f"Start-Sleep -Milliseconds {int(seconds * 1000)}; "
            "$p.Stop(); $p.Close(); "
            f"Remove-Item -LiteralPath '{escaped}' -ErrorAction SilentlyContinue"
        )
        with self._lock:
            self._stop_event.clear()
            self._proc = subprocess.Popen(
                ["powershell", "-Command", ps],
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        try:
            self._proc.wait(timeout=seconds + 5)
        except subprocess.TimeoutExpired:
            self._proc.kill()
        finally:
            with self._lock:
                self._proc = None

    def _speak_clone(self, text: str):
        safe_text = text.encode("ascii", "ignore").decode("ascii")
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
            media_path = f.name
        cmd = [
            sys.executable,
            "-m",
            "jarvis_ai.voice_clone",
            "--text",
            safe_text,
            "--out",
            media_path,
        ]
        try:
            subprocess.run(
                cmd,
                cwd=str(config.BASE_DIR.parent),
                capture_output=True,
                text=True,
                timeout=config.CLONE_TTS_TIMEOUT_SECONDS,
                check=True,
            )
            seconds = max(2.0, min(30.0, len(safe_text.split()) / 2.4 + 0.8))
            self._play_media_file(media_path, seconds)
        except Exception as e:
            try:
                os.unlink(media_path)
            except OSError:
                pass
            if config.CLONE_TTS_STRICT:
                print(f"[mouth] clone TTS unavailable ({e}); strict clone mode, staying silent")
            else:
                print(f"[mouth] clone TTS unavailable ({e}); using Edge neural voice")
                self._speak_edge(safe_text)

    def _speak_hf(self, text: str):
        safe_text = text.encode("ascii", "ignore").decode("ascii")
        endpoint = config.HF_TTS_ENDPOINT_URL
        if not endpoint and config.HF_TTS_MODEL:
            endpoint = "https://api-inference.huggingface.co/models/" + config.HF_TTS_MODEL
        if not endpoint:
            print("[mouth] HF_TTS_ENDPOINT_URL or HF_TTS_MODEL is not configured")
            if config.HF_TTS_FALLBACK_TO_EDGE:
                self._speak_edge(safe_text)
            return

        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
            media_path = f.name
        try:
            import requests

            headers = {"Accept": "audio/wav"}
            if config.HF_TOKEN:
                headers["Authorization"] = f"Bearer {config.HF_TOKEN}"
            payload = {
                "inputs": safe_text,
                "parameters": {
                    "reference_audio": config.CLONE_TTS_REFERENCE,
                    "voice": config.ASSISTANT_NAME,
                },
            }
            response = requests.post(
                endpoint,
                headers=headers,
                json=payload,
                timeout=config.HF_TTS_TIMEOUT_SECONDS,
            )
            content_type = response.headers.get("content-type", "")
            if not response.ok:
                raise RuntimeError(f"HTTP {response.status_code}: {response.text[:200]}")
            if "application/json" in content_type:
                raise RuntimeError(f"Expected audio, got JSON: {response.text[:200]}")
            with open(media_path, "wb") as out:
                out.write(response.content)
            seconds = max(2.0, min(30.0, len(safe_text.split()) / 2.4 + 0.8))
            self._play_media_file(media_path, seconds)
        except Exception as e:
            try:
                os.unlink(media_path)
            except OSError:
                pass
            print(f"[mouth] Hugging Face TTS unavailable ({e})")
            if config.HF_TTS_FALLBACK_TO_EDGE:
                self._speak_edge(safe_text)

    def _speak_edge(self, text: str):
        safe_text = text.encode("ascii", "ignore").decode("ascii")
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as f:
            media_path = f.name

        async def _save():
            import edge_tts
            communicate = edge_tts.Communicate(
                safe_text,
                config.EDGE_TTS_VOICE,
                rate=config.EDGE_TTS_RATE,
                pitch=config.EDGE_TTS_PITCH,
            )
            await communicate.save(media_path)

        try:
            asyncio.run(_save())
        except Exception as e:
            print(
                "[mouth] edge-tts error: "
                f"{e}; using female Windows fallback "
                f"({getattr(config, 'POWERSHELL_TTS_VOICE', 'first installed female voice')})"
            )
            self._speak_powershell(safe_text)
            return

        seconds = max(2.0, min(30.0, len(safe_text.split()) / 2.4 + 0.8))
        self._play_media_file(media_path, seconds)

    def _say_piper(self, text: str):
        import numpy as np
        import sounddevice as sd
        sr = self.voice.config.sample_rate
        stream = sd.OutputStream(samplerate=sr, channels=1, dtype="int16")
        stream.start()
        try:
            for chunk in self.voice.synthesize_stream_raw(text):
                if self._stop_event.is_set():
                    break
                stream.write(np.frombuffer(chunk, dtype=np.int16))
        finally:
            stream.stop()
            stream.close()

    def say_stream(self, token_gen) -> str:
        """Consume a token generator, speak at sentence boundaries for fast perceived latency.

        Starts TTS generation after first ~6 words or sentence end.
        Plays chunks sequentially (no interruption between sentences).
        Returns the full text spoken.
        """
        # A voice clone is synthesized as a complete audio file. Starting it on
        # partial streamed text means a later cloud fallback can become a second
        # overlapping reply. Buffer it and speak exactly once instead.
        if self.engine_name == "clone":
            full_text = "".join(token_gen).strip()
            if full_text:
                self.say(full_text)
            return full_text

        PUNCT = set(".!?,;")
        MIN_WORDS = 6

        buffer = ""
        full_text = ""
        first_chunk = True

        for token in token_gen:
            buffer += token
            words = buffer.split()
            ends = bool(buffer.rstrip()) and buffer.rstrip()[-1] in PUNCT

            if (ends and len(words) >= MIN_WORDS) or len(words) >= 14:
                chunk = buffer.strip()
                buffer = ""
                if chunk:
                    full_text += (" " if full_text else "") + chunk
                    print(f"{config.ASSISTANT_NAME}: {chunk}", flush=True)
                    if first_chunk:
                        # First chunk: interrupt any previous speech, start immediately
                        self.stop()
                        first_chunk = False
                    else:
                        # Wait for previous chunk to finish before queuing next
                        self.join(timeout=15)
                    self._start_tts_thread(chunk)

        if buffer.strip():
            chunk = buffer.strip()
            full_text += (" " if full_text else "") + chunk
            print(f"{config.ASSISTANT_NAME}: {chunk}", flush=True)
            if first_chunk:
                self.stop()
            else:
                self.join(timeout=15)
            self._start_tts_thread(chunk)

        return full_text

    def _start_tts_thread(self, text: str):
        """Launch TTS for one chunk in a background thread (non-interrupting)."""
        import threading
        if self.engine_name == "edge":
            self._speak_thread = threading.Thread(
                target=self._speak_edge, args=(text,), daemon=True
            )
        elif self.engine_name == "clone":
            self._speak_thread = threading.Thread(
                target=self._speak_clone, args=(text,), daemon=True
            )
        elif self.engine_name == "hf":
            self._speak_thread = threading.Thread(
                target=self._speak_hf, args=(text,), daemon=True
            )
        elif self.engine_name == "pyttsx3":
            def _run():
                try:
                    self.engine.say(text)
                    self.engine.runAndWait()
                except Exception as e:
                    print(f"[mouth] pyttsx3 error: {e}")
            self._speak_thread = threading.Thread(target=_run, daemon=True)
        else:
            self._speak_thread = threading.Thread(
                target=self._speak_powershell, args=(text,), daemon=True
            )
        self._speak_thread.start()

    def say(self, text: str, wait: bool = False):
        if not text:
            return
        safe_text = text.encode("ascii", "ignore").decode("ascii")
        print(f"{config.ASSISTANT_NAME}: {safe_text}")
        # interrupt any previous speech
        self.stop()
        if self.engine_name == "piper":
            self._speak_thread = threading.Thread(
                target=self._say_piper, args=(safe_text,), daemon=True
            )
            self._speak_thread.start()
        elif self.engine_name == "clone":
            self._speak_thread = threading.Thread(
                target=self._speak_clone, args=(safe_text,), daemon=True
            )
            self._speak_thread.start()
        elif self.engine_name == "hf":
            self._speak_thread = threading.Thread(
                target=self._speak_hf, args=(safe_text,), daemon=True
            )
            self._speak_thread.start()
        elif self.engine_name == "edge":
            self._speak_thread = threading.Thread(
                target=self._speak_edge, args=(safe_text,), daemon=True
            )
            self._speak_thread.start()
        elif self.engine_name == "pyttsx3":
            def _run():
                try:
                    self.engine.say(safe_text)
                    self.engine.runAndWait()
                except Exception as e:
                    print(f"[mouth] pyttsx3 error: {e}")
            self._speak_thread = threading.Thread(target=_run, daemon=True)
            self._speak_thread.start()
        else:
            self._speak_thread = threading.Thread(
                target=self._speak_powershell, args=(safe_text,), daemon=True
            )
            self._speak_thread.start()
        if wait:
            self.join()
