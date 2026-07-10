"""Text-to-speech with interrupt support."""
import asyncio
import os
import tempfile
import subprocess
import threading
import time
import sys
import queue
import numpy as np
from . import config
from . import language
from .runtime_state import runtime


def clone_cache_key(text: str) -> str:
    """Stable cache filename stem for a spoken phrase (case/punct-insensitive)."""
    import hashlib
    import re
    norm = " ".join(re.sub(r"[^a-z0-9\s]", "", (text or "").lower()).split())
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:16] if norm else ""


def _clone_cached_path(text: str) -> str | None:
    """Path to a pre-rendered owner-voice WAV for this exact phrase, if any."""
    if not getattr(config, "CLONE_PHRASE_CACHE_ENABLED", False):
        return None
    key = clone_cache_key(text)
    if not key:
        return None
    path = os.path.join(getattr(config, "CLONE_PHRASE_CACHE_DIR", ""), f"{key}.wav")
    return path if path and os.path.isfile(path) else None


def _elevenlabs_cache_path(text: str) -> str | None:
    """Private cache path for short fixed phrases in the active clone."""
    import hashlib
    import re

    normalized = " ".join(re.sub(r"[^a-z0-9\s]", "", (text or "").lower()).split())
    allowed = getattr(config, "ELEVENLABS_CACHE_PHRASES", set())
    if not normalized or normalized not in allowed or not config.ELEVENLABS_VOICE_ID:
        return None
    identity = (
        f"{config.ELEVENLABS_VOICE_ID}:{config.ELEVENLABS_MODEL}:"
        f"{config.ELEVENLABS_OUTPUT_GAIN}:{normalized}"
    )
    key = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    return os.path.join(config.ELEVENLABS_PHRASE_CACHE_DIR, f"{key}.wav")


class Mouth:
    def __init__(self):
        self._lock = threading.Lock()
        self._proc = None
        self._stop_event = threading.Event()
        self._speak_thread = None
        self._stream_active = threading.Event()
        self._generation = 0
        self.engine_name = config.TTS_ENGINE
        if self.engine_name == "piper":
            self._init_piper()
        elif self.engine_name == "clone":
            self.engine = None
        elif self.engine_name == "hf":
            self.engine = None
        elif self.engine_name == "elevenlabs":
            self.engine = None
            print("[mouth] TTS engine: ElevenLabs cloned voice (streaming)")
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
            self._generation += 1
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
        try:
            import sounddevice as sd
            sd.stop()
        except Exception:
            pass
        if os.name == "nt":
            try:
                import winsound
                winsound.PlaySound(None, winsound.SND_PURGE)
            except Exception:
                pass

    def is_speaking(self) -> bool:
        return self._stream_active.is_set() or (
            self._speak_thread is not None and self._speak_thread.is_alive()
        )

    def join(self, timeout: float = 30.0):
        if self._speak_thread:
            self._speak_thread.join(timeout=timeout)

    def _active_generation(self) -> int:
        with self._lock:
            return self._generation

    def _is_current(self, generation: int | None) -> bool:
        with self._lock:
            return generation is None or generation == self._generation

    def _speak_powershell(self, text: str):
        safe_text = text
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
                # WPF MediaPlayer requires an STA apartment. Without -STA the
                # Edge MP3 is generated but may play silently on Windows.
                ["powershell", "-NoProfile", "-STA", "-Command", ps],
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
        """Play generated audio in-process so stale PowerShell players cannot overlap."""
        try:
            import sounddevice as sd
            import soundfile as sf

            audio, sample_rate = sf.read(media_path, dtype="float32", always_2d=True)
            with self._lock:
                self._stop_event.clear()
            sd.play(audio, sample_rate, device=config.OUTPUT_DEVICE)
            sd.wait()
        finally:
            try:
                os.unlink(media_path)
            except OSError:
                pass

    def _play_edge_file(self, media_path: str, seconds: float, generation: int | None = None):
        """Play Edge MP3 through Windows' active speaker/headphone route."""
        if not self._is_current(generation):
            try:
                os.unlink(media_path)
            except OSError:
                pass
            return
        try:
            import sounddevice as sd
            import soundfile as sf

            audio, sample_rate = sf.read(media_path, dtype="float32", always_2d=True)
            with self._lock:
                if generation is not None and generation != self._generation:
                    os.unlink(media_path)
                    return
                self._stop_event.clear()
            sd.play(audio, sample_rate, device=config.OUTPUT_DEVICE)
            sd.wait()
            try:
                os.unlink(media_path)
            except OSError:
                pass
            return
        except Exception as e:
            print(f"[mouth] direct Edge playback failed ({e}); falling back to Windows MediaPlayer")

        escaped = media_path.replace("'", "''")
        ps = (
            "Add-Type -AssemblyName PresentationCore; "
            "$p = New-Object System.Windows.Media.MediaPlayer; "
            f"$p.Open([Uri]'{escaped}'); "
            "$deadline = (Get-Date).AddSeconds(3); "
            "while (-not $p.NaturalDuration.HasTimeSpan -and (Get-Date) -lt $deadline) "
            "{ Start-Sleep -Milliseconds 50 }; "
            f"$fallbackMs = {int(seconds * 1000)}; "
            "$playMs = if ($p.NaturalDuration.HasTimeSpan) "
            "{ [Math]::Ceiling($p.NaturalDuration.TimeSpan.TotalMilliseconds) + 500 } "
            "else { $fallbackMs }; "
            "$p.Play(); Start-Sleep -Milliseconds $playMs; "
            "$p.Stop(); $p.Close(); "
            f"Remove-Item -LiteralPath '{escaped}' -ErrorAction SilentlyContinue"
        )
        with self._lock:
            if generation is not None and generation != self._generation:
                try:
                    os.unlink(media_path)
                except OSError:
                    pass
                return
            self._stop_event.clear()
            proc = subprocess.Popen(
                ["powershell", "-NoProfile", "-STA", "-Command", ps],
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            self._proc = proc
        try:
            proc.wait(timeout=seconds + 5)
        except subprocess.TimeoutExpired:
            proc.kill()
        finally:
            with self._lock:
                if self._proc is proc:
                    self._proc = None

    def _speak_clone(self, text: str):
        safe_text = text
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
        clone_proc = None
        try:
            # Keep the clone worker under the same interruption controller as
            # media playback. Previously subprocess.run() was invisible to
            # stop(), so old clone jobs survived a new command and played late.
            clone_proc = subprocess.Popen(
                cmd,
                cwd=str(config.BASE_DIR.parent),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            with self._lock:
                self._proc = clone_proc
            stdout, stderr = clone_proc.communicate(timeout=config.CLONE_TTS_TIMEOUT_SECONDS)
            if clone_proc.returncode:
                raise subprocess.CalledProcessError(
                    clone_proc.returncode, cmd, output=stdout, stderr=stderr
                )
            seconds = max(2.0, min(30.0, len(safe_text.split()) / 2.4 + 0.8))
            self._play_media_file(media_path, seconds)
        except Exception as e:
            if isinstance(e, subprocess.TimeoutExpired) and clone_proc:
                clone_proc.kill()
                clone_proc.communicate()
            try:
                os.unlink(media_path)
            except OSError:
                pass
            if config.CLONE_TTS_STRICT:
                print(f"[mouth] clone TTS unavailable ({e}); strict clone mode, staying silent")
            else:
                print(f"[mouth] clone TTS unavailable ({e}); using Edge neural voice")
                self._speak_edge(safe_text)
        finally:
            with self._lock:
                if self._proc is clone_proc:
                    self._proc = None

    def _speak_hf(self, text: str):
        safe_text = text
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

    def _play_cached_clone(self, path: str, generation: int | None = None) -> bool:
        """Play a pre-rendered owner-voice phrase from disk (never deleted)."""
        if not self._is_current(generation):
            return True
        try:
            import sounddevice as sd
            import soundfile as sf

            audio, sample_rate = sf.read(path, dtype="float32", always_2d=True)
            with self._lock:
                if generation is not None and generation != self._generation:
                    return True
                self._stop_event.clear()
            sd.play(audio, sample_rate, device=config.OUTPUT_DEVICE)
            sd.wait()
            return True
        except Exception as e:
            print(f"[mouth] clone cache playback failed ({e}); using Edge voice")
            return False

    def _play_elevenlabs_cache(self, path: str, generation: int | None = None) -> bool:
        """Play a fixed cloned phrase through Leha's selected endpoint."""
        if not self._is_current(generation):
            return True
        try:
            if config.OUTPUT_DEVICE is not None:
                import sounddevice as sd
                import soundfile as sf

                audio, sample_rate = sf.read(path, dtype="float32", always_2d=True)
                sd.play(audio, sample_rate, device=config.OUTPUT_DEVICE)
                sd.wait()
            elif os.name == "nt":
                import winsound

                winsound.PlaySound(path, winsound.SND_FILENAME)
            else:
                return self._play_cached_clone(path, generation)
            print("[mouth] ElevenLabs cached playback completed", flush=True)
            return True
        except Exception as e:
            print(f"[mouth] Windows cached playback failed ({e}); using direct output")
            return self._play_cached_clone(path, generation)

    def _speak_elevenlabs(self, text: str, generation: int | None = None):
        """Stream the cloned voice directly to the speaker.

        Edge is used only when ElevenLabs fails before cloned audio starts.
        Switching voices after partial playback would sound like a duplicate
        reply, so a mid-stream failure ends the current utterance instead.
        """
        safe_text = text
        cached_path = _elevenlabs_cache_path(safe_text)
        if cached_path and os.path.isfile(cached_path):
            started = time.perf_counter()
            if self._play_elevenlabs_cache(cached_path, generation):
                runtime.timing("tts_first_audio", (time.perf_counter() - started) * 1000)
                return
        audio_started = False
        completed = False
        response = None
        output = None
        cache_chunks = [] if cached_path else None
        started = time.perf_counter()
        try:
            import requests
            import sounddevice as sd

            url = (
                "https://api.elevenlabs.io/v1/text-to-speech/"
                f"{config.ELEVENLABS_VOICE_ID}/stream?output_format=pcm_24000"
            )
            response = requests.post(
                url,
                headers={
                    "xi-api-key": config.ELEVENLABS_API_KEY,
                    "Content-Type": "application/json",
                    "Accept": "audio/pcm",
                },
                json={
                    "text": safe_text,
                    "model_id": config.ELEVENLABS_MODEL,
                    "voice_settings": {
                        "stability": config.ELEVENLABS_STABILITY,
                        "similarity_boost": config.ELEVENLABS_SIMILARITY_BOOST,
                        "style": config.ELEVENLABS_STYLE,
                        "use_speaker_boost": config.ELEVENLABS_SPEAKER_BOOST,
                    },
                },
                stream=True,
                timeout=config.ELEVENLABS_TIMEOUT_SECONDS,
            )
            if not response.ok:
                raise RuntimeError(f"HTTP {response.status_code}")
            if not self._is_current(generation):
                return

            with self._lock:
                if generation is not None and generation != self._generation:
                    return
                self._stop_event.clear()

            output = sd.RawOutputStream(
                samplerate=24000,
                channels=1,
                dtype="int16",
                device=config.OUTPUT_DEVICE,
            )
            output.start()
            carry = b""
            for chunk in response.iter_content(chunk_size=4096):
                if not chunk:
                    continue
                if self._stop_event.is_set() or not self._is_current(generation):
                    break
                chunk = carry + chunk
                if len(chunk) % 2:
                    carry, chunk = chunk[-1:], chunk[:-1]
                else:
                    carry = b""
                if chunk:
                    gain = max(0.1, float(getattr(config, "ELEVENLABS_OUTPUT_GAIN", 1.0)))
                    if gain != 1.0:
                        samples = np.frombuffer(chunk, dtype=np.int16).astype(np.float32)
                        samples = np.clip(samples * gain, -32768, 32767).astype(np.int16)
                        chunk = samples.tobytes()
                    output.write(chunk)
                    if cache_chunks is not None:
                        cache_chunks.append(chunk)
                    if not audio_started:
                        audio_started = True
                        runtime.timing(
                            "tts_first_audio", (time.perf_counter() - started) * 1000
                        )
            completed = not self._stop_event.is_set() and self._is_current(generation)
            runtime.timing("tts_generate", (time.perf_counter() - started) * 1000)
            if completed:
                print("[mouth] ElevenLabs streamed playback completed", flush=True)
        except Exception as e:
            if audio_started:
                print(f"[mouth] ElevenLabs stream ended early ({e})")
            elif self._is_current(generation):
                print(f"[mouth] ElevenLabs unavailable ({e}); using Edge voice")
                self._speak_edge(safe_text, generation)
        finally:
            if output is not None:
                try:
                    output.stop()
                except Exception:
                    pass
                try:
                    output.close()
                except Exception:
                    pass
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass
            if completed and cache_chunks and cached_path:
                try:
                    import soundfile as sf

                    os.makedirs(os.path.dirname(cached_path), exist_ok=True)
                    pcm = np.frombuffer(b"".join(cache_chunks), dtype=np.int16)
                    sf.write(cached_path, pcm, 24000, subtype="PCM_16")
                except Exception as e:
                    print(f"[mouth] fixed-phrase cache write failed ({e})")

    def _speak_edge(self, text: str, generation: int | None = None):
        safe_text = text
        cached = _clone_cached_path(safe_text)
        if cached and self._play_cached_clone(cached, generation):
            return
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as f:
            media_path = f.name

        async def _save():
            import edge_tts
            voice = language.edge_voice_for_text(safe_text)
            communicate = edge_tts.Communicate(
                safe_text,
                voice or config.EDGE_TTS_VOICE,
                rate=config.EDGE_TTS_RATE,
                pitch=config.EDGE_TTS_PITCH,
            )
            await communicate.save(media_path)

        generated_started = time.perf_counter()
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

        runtime.timing("tts_generate", (time.perf_counter() - generated_started) * 1000)

        if not self._is_current(generation):
            try:
                os.unlink(media_path)
            except OSError:
                pass
            return

        # Fallback only when MediaPlayer cannot read MP3 duration. Bias long so
        # an answer is never cut off mid-sentence during a slow audio startup.
        seconds = max(3.0, min(60.0, len(safe_text.split()) / 1.6 + 2.0))
        self._play_edge_file(media_path, seconds, generation)

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
        """Pipeline streamed text into one sequential, cancellable voice.

        Token generation and audio playback run concurrently. This prevents a
        slow spoken first sentence from pausing the provider's HTTP stream,
        while the bounded queue avoids buffering an unlimited reply.
        """
        # A voice clone is synthesized as a complete audio file. Starting it on
        # partial streamed text means a later cloud fallback can become a second
        # overlapping reply. Buffer it and speak exactly once instead.
        if self.engine_name == "clone":
            full_text = "".join(token_gen).strip()
            if full_text:
                self.say(full_text)
            return full_text

        punct = set(".!?,;")
        min_words = max(2, int(getattr(config, "TTS_STREAM_FIRST_WORDS", 5)))
        max_words = max(min_words, int(getattr(config, "TTS_STREAM_MAX_WORDS", 16)))
        chunk_queue: queue.Queue = queue.Queue(
            maxsize=max(1, int(getattr(config, "TTS_STREAM_QUEUE_MAX", 4)))
        )
        sentinel = object()
        playback_failed = threading.Event()
        buffer = ""
        full_text = ""
        self.stop()
        generation = self._active_generation()
        self._stream_active.set()

        def speak_blocking(chunk: str):
            if self.engine_name == "elevenlabs":
                self._speak_elevenlabs(chunk, generation)
            elif self.engine_name == "edge":
                self._speak_edge(chunk, generation)
            elif self.engine_name == "hf":
                self._speak_hf(chunk)
            elif self.engine_name == "piper":
                self._say_piper(chunk)
            elif self.engine_name == "pyttsx3":
                self.engine.say(chunk)
                self.engine.runAndWait()
            else:
                self._speak_powershell(chunk)

        def playback_loop():
            try:
                while self._is_current(generation):
                    item = chunk_queue.get()
                    if item is sentinel:
                        return
                    print(f"{config.ASSISTANT_NAME}: {item}", flush=True)
                    speak_blocking(item)
            except Exception as exc:
                playback_failed.set()
                print(f"[mouth] streamed playback stopped ({exc})", flush=True)
            finally:
                self._stream_active.clear()

        worker = threading.Thread(target=playback_loop, daemon=True)
        self._speak_thread = worker
        worker.start()

        def enqueue(item) -> bool:
            while self._is_current(generation) and not playback_failed.is_set():
                try:
                    chunk_queue.put(item, timeout=0.1)
                    return True
                except queue.Full:
                    if not worker.is_alive():
                        playback_failed.set()
                        return False
                    continue
            return False

        try:
            for token in token_gen:
                if not self._is_current(generation):
                    break
                buffer += token
                words = buffer.split()
                ends = bool(buffer.rstrip()) and buffer.rstrip()[-1] in punct
                if (ends and len(words) >= min_words) or len(words) >= max_words:
                    chunk = buffer.strip()
                    buffer = ""
                    if chunk and enqueue(chunk):
                        full_text += (" " if full_text else "") + chunk

            if buffer.strip() and self._is_current(generation):
                chunk = buffer.strip()
                if enqueue(chunk):
                    full_text += (" " if full_text else "") + chunk
        finally:
            enqueue(sentinel)
            worker.join(timeout=float(getattr(config, "TTS_STREAM_DRAIN_SECONDS", 90)))
            if worker.is_alive():
                self.stop()
            self._stream_active.clear()
            if self._speak_thread is worker:
                self._speak_thread = None

        return full_text

    def _start_tts_thread(self, text: str, generation: int | None = None):
        """Launch TTS for one chunk in a background thread (non-interrupting)."""
        import threading
        if self.engine_name == "elevenlabs":
            self._speak_thread = threading.Thread(
                target=self._speak_elevenlabs, args=(text, generation), daemon=True
            )
        elif self.engine_name == "edge":
            self._speak_thread = threading.Thread(
                target=self._speak_edge, args=(text, generation), daemon=True
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
        safe_text = text
        print(f"{config.ASSISTANT_NAME}: {safe_text}")
        # interrupt any previous speech
        self.stop()
        generation = self._active_generation()
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
        elif self.engine_name == "elevenlabs":
            self._speak_thread = threading.Thread(
                target=self._speak_elevenlabs, args=(safe_text, generation), daemon=True
            )
            self._speak_thread.start()
        elif self.engine_name == "edge":
            self._speak_thread = threading.Thread(
                target=self._speak_edge, args=(safe_text, generation), daemon=True
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
