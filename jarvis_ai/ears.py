"""Speech-to-text with Deepgram, OpenAI, Groq, and local Whisper providers."""
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np

from . import config

_GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
_OPENAI_URL = "https://api.openai.com/v1/audio/transcriptions"
_DEEPGRAM_URL = "https://api.deepgram.com/v1/listen"
_INDIC_CODEPOINT_RANGES = (
    ("ऀ", "ॿ"), ("ঀ", "৿"), ("઀", "૿"),
    ("଀", "୿"), ("஀", "௿"), ("ఀ", "౿"),
    ("ಀ", "೿"), ("ഀ", "ൿ"),
)


def _has_indic_script(text: str) -> bool:
    # Override any accidentally mojibaked literal ranges above with numeric
    # Unicode blocks. This keeps Indic detection independent of file encoding.
    indic_ranges = (
        (0x0900, 0x097F),  # Devanagari: Hindi/Marathi
        (0x0980, 0x09FF),  # Bengali
        (0x0A00, 0x0A7F),  # Gurmukhi/Punjabi
        (0x0A80, 0x0AFF),  # Gujarati
        (0x0B00, 0x0B7F),  # Odia
        (0x0B80, 0x0BFF),  # Tamil
        (0x0C00, 0x0C7F),  # Telugu
        (0x0C80, 0x0CFF),  # Kannada
        (0x0D00, 0x0D7F),  # Malayalam
    )
    return any(
        start <= ord(ch) <= end
        for ch in (text or "")
        for start, end in indic_ranges
    )


class Ears:
    def __init__(self):
        requested = config.STT_ENGINE
        self.engine = self._select_engine(requested)
        self._disabled_providers: set[str] = set()
        self._provider_order = self._provider_candidates(self.engine)
        self.model = None
        if self.engine == "deepgram":
            print(f"[ears] STT engine: Deepgram cloud ({config.DEEPGRAM_STT_MODEL})")
        elif self.engine == "openai":
            print(f"[ears] STT engine: OpenAI cloud ({config.OPENAI_STT_MODEL})")
        elif self.engine == "groq":
            print(f"[ears] STT engine: Groq cloud ({config.GROQ_STT_MODEL})")
        elif self.engine == "sarvam":
            print(f"[ears] STT engine: Sarvam cloud ({config.SARVAM_STT_MODEL})")
        else:
            if requested != "local":
                print(f"[ears] {requested} is not configured -> falling back to local Whisper")
            self._ensure_local()

    @staticmethod
    def _select_engine(requested: str) -> str:
        requested = (requested or "auto").lower()
        available = {
            "deepgram": bool(config.DEEPGRAM_API_KEY),
            "sarvam": bool(getattr(config, "SARVAM_API_KEY", "")),
            "openai": bool(config.OPENAI_API_KEY),
            "groq": bool(config.GROQ_API_KEY),
        }
        if requested == "auto":
            for name in ("deepgram", "sarvam", "openai", "groq"):
                if available[name]:
                    return name
            return "local"
        if requested in available and available[requested]:
            return requested
        return "local"

    def _provider_candidates(self, primary: str) -> list[str]:
        # Sarvam saarika sits right after Deepgram: when Deepgram returns
        # nothing (common for short Indian-language clips), the Indian-language
        # specialist gets the next attempt before generic Whisper providers.
        providers = ["deepgram", "sarvam", "groq", "openai"]
        available = {
            "deepgram": bool(config.DEEPGRAM_API_KEY),
            "sarvam": bool(getattr(config, "SARVAM_API_KEY", "")),
            "openai": bool(config.OPENAI_API_KEY),
            "groq": bool(config.GROQ_API_KEY),
        }
        if primary not in providers:
            return []
        # A deliberately selected provider should be decisive. Falling through
        # to unrelated cloud providers after an empty result adds many seconds
        # and can surface stale/invalid keys. Multi-provider behavior remains
        # available only when STT_ENGINE is explicitly set to "auto".
        if (config.STT_ENGINE or "").lower() != "auto":
            return [primary] if available[primary] and primary not in self._disabled_providers else []
        ordered = [primary] + [name for name in providers if name != primary]
        return [name for name in ordered if available[name] and name not in self._disabled_providers]

    def _disable_provider(self, provider: str) -> None:
        self._disabled_providers.add(provider)
        self._provider_order = self._provider_candidates(self.engine)

    def _ensure_local(self) -> None:
        if self.model is not None:
            return
        self.engine = "local"
        print(f"[ears] loading local whisper '{config.WHISPER_MODEL}' ...")
        from faster_whisper import WhisperModel
        self.model = WhisperModel(
            config.WHISPER_MODEL,
            device=config.WHISPER_DEVICE,
            compute_type=config.WHISPER_COMPUTE,
        )

    # ---- Groq cloud ----
    def _groq(self, path: str) -> str:
        import requests
        try:
            data = {
                "model": config.GROQ_STT_MODEL,
                "prompt": (
                    "Leha. Indian multilingual assistant. Hindi, Telugu, Tamil, "
                    "Kannada, Malayalam, Marathi, Gujarati, Bengali, Hinglish, English."
                ),
                "response_format": "text",
            }
            if config.WHISPER_LANG:
                data["language"] = config.WHISPER_LANG
            with open(path, "rb") as f:
                r = requests.post(
                    _GROQ_URL,
                    headers={"Authorization": f"Bearer {config.GROQ_API_KEY}"},
                    files={"file": (os.path.basename(path), f, "application/octet-stream")},
                    data=data,
                    timeout=config.STT_REQUEST_TIMEOUT_SECONDS,
                )
            return r.text.strip() if r.ok else ""
        except Exception as e:
            print(f"[ears] groq error: {e}")
            return ""

    def _openai(self, path: str) -> str:
        import requests
        try:
            data = {
                "model": config.OPENAI_STT_MODEL,
                "response_format": "json",
            }
            if config.WHISPER_LANG:
                data["language"] = config.WHISPER_LANG
            with open(path, "rb") as f:
                r = requests.post(
                    _OPENAI_URL,
                    headers={"Authorization": f"Bearer {config.OPENAI_API_KEY}"},
                    files={"file": (os.path.basename(path), f, "audio/wav")},
                    data=data,
                    timeout=config.STT_REQUEST_TIMEOUT_SECONDS,
                )
            if not r.ok:
                print(f"[ears] OpenAI error {r.status_code}: {r.text[:160]}")
                if r.status_code in {401, 403}:
                    self._disable_provider("openai")
                return ""
            return (r.json().get("text") or "").strip()
        except Exception as e:
            print(f"[ears] OpenAI error: {e}")
            return ""

    def _deepgram(self, path: str, language_fallback: bool = False, wake_bias: bool = False) -> str:
        import requests
        params = {
            "model": config.DEEPGRAM_STT_MODEL,
            "smart_format": "true",
            "punctuate": "true",
        }
        if wake_bias:
            params["language"] = "en"
            keywords = [
                item.strip()
                for item in getattr(config, "DEEPGRAM_WAKE_KEYWORDS", "").split(",")
                if item.strip()
            ]
            if keywords:
                # Deepgram Nova-3 uses `keyterm`, not the older `keywords`
                # query parameter. requests expands the list safely.
                params["keyterm"] = keywords
        elif config.WHISPER_LANG:
            params["language"] = config.WHISPER_LANG
        elif not language_fallback:
            params["detect_language"] = "true"
        else:
            params["language"] = "en"
        try:
            with open(path, "rb") as f:
                r = requests.post(
                    _DEEPGRAM_URL,
                    headers={
                        "Authorization": f"Token {config.DEEPGRAM_API_KEY}",
                        "Content-Type": "audio/wav",
                    },
                    params=params,
                    data=f,
                    timeout=(
                        config.STT_WAKE_REQUEST_TIMEOUT_SECONDS
                        if wake_bias else config.STT_REQUEST_TIMEOUT_SECONDS
                    ),
                )
            if not r.ok:
                print(f"[ears] Deepgram error {r.status_code}: {r.text[:160]}")
                if r.status_code in {401, 403}:
                    self._disable_provider("deepgram")
                return ""
            channels = r.json().get("results", {}).get("channels", [])
            alternatives = channels[0].get("alternatives", []) if channels else []
            text = (alternatives[0].get("transcript") or "").strip() if alternatives else ""
            try:
                self._last_deepgram_confidence = float(alternatives[0].get("confidence", 1.0)) if alternatives else 0.0
            except (TypeError, ValueError):
                self._last_deepgram_confidence = 1.0

            # If detect_language failed on a short audio clip (like just the wake word), retry in English
            if not text and not language_fallback and not config.WHISPER_LANG:
                return self._deepgram(path, language_fallback=True)

            return text
        except Exception as e:
            print(f"[ears] Deepgram error: {e}")
            return ""

    def _sarvam(self, path: str) -> str:
        """Sarvam saarika STT — Indian-language specialist (auto-detects
        Telugu, Hindi, Tamil, Kannada, Malayalam, and code-mixed English)."""
        import requests
        try:
            with open(path, "rb") as f:
                r = requests.post(
                    config.SARVAM_STT_URL,
                    headers={"api-subscription-key": config.SARVAM_API_KEY},
                    files={"file": (os.path.basename(path), f, "audio/wav")},
                    data={
                        "model": config.SARVAM_STT_MODEL,
                        "language_code": "unknown",
                    },
                    timeout=config.STT_REQUEST_TIMEOUT_SECONDS,
                )
            if not r.ok:
                print(f"[ears] Sarvam error {r.status_code}: {r.text[:160]}")
                if r.status_code in {401, 403}:
                    self._disable_provider("sarvam")
                return ""
            return (r.json().get("transcript") or "").strip()
        except Exception as e:
            print(f"[ears] Sarvam error: {e}")
            return ""

    # ---- local ----
    def _local_file(self, path: str) -> str:
        segments, _ = self.model.transcribe(
            path, beam_size=1, language=config.WHISPER_LANG, vad_filter=True
        )
        return "".join(s.text for s in segments).strip()

    # ---- public API ----
    def transcribe_file(self, path: str, *, rescue_indian: bool = True) -> str:
        providers = list(self._provider_order)
        for provider in providers:
            if provider == "deepgram":
                text = self._deepgram(path)
                if rescue_indian:
                    text = self._rescue_indian_speech(path, text)
            elif provider == "sarvam":
                text = self._sarvam(path)
            elif provider == "openai":
                text = self._openai(path)
            else:
                text = self._groq(path)
            if text:
                if provider != self.engine:
                    # An empty/noisy clip is not evidence that the configured
                    # primary is unhealthy. Use this fallback for the current
                    # utterance only; permanent promotion used to disable the
                    # Deepgram wake-biased retry after one silent clip.
                    print(f"[ears] STT fallback used for this utterance: {provider}")
                return text
        return self._finish_transcribe_file(path)

    def _rescue_indian_speech(self, path: str, text: str) -> str:
        """Re-check low-confidence Deepgram output with Sarvam saarika.

        Deepgram nova-3 has no Telugu/Tamil/Kannada support, so Indian speech
        comes back as low-confidence English-looking noise. When confidence is
        below the configured floor and Sarvam is available, saarika's
        transcript (native Indian script) wins if it produces anything.
        """
        if not text or not getattr(config, "SARVAM_API_KEY", ""):
            return text
        if _has_indic_script(text):
            return text
        # Skip the rescue for very short clips (bare wake words): a second
        # cloud call there only delays wake handling — observed +3s when the
        # Sarvam API was slow. 16kHz/16-bit mono WAV is ~32KB per second.
        try:
            if os.path.getsize(path) < 48_000:
                return text
        except OSError:
            pass
        confidence = getattr(self, "_last_deepgram_confidence", 1.0)
        if confidence >= getattr(config, "STT_DEEPGRAM_MIN_CONFIDENCE", 0.60):
            return text
        rescued = self._sarvam(path)
        if rescued:
            print(f"[ears] Deepgram confidence {confidence:.2f} -> using Sarvam: {rescued[:60]}")
            return rescued
        return text

    def _finish_transcribe_file(self, path: str) -> str:
        if self.engine != "local" and config.STT_CLOUD_FALLBACK_TO_LOCAL:
            print("[ears] cloud transcription unavailable -> local Whisper fallback")
            self._ensure_local()
            return self._local_file(path)
        return self._local_file(path) if self.engine == "local" else ""

    def transcribe_int16(self, audio_int16: np.ndarray, *, rescue_indian: bool = True) -> str:
        """Transcribe a raw int16 mono buffer (16 kHz) from the mic."""
        if self.engine != "local":
            import soundfile as sf
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
                path = f.name
            try:
                sf.write(path, audio_int16, config.SAMPLE_RATE)
                return self.transcribe_file(path, rescue_indian=rescue_indian)
            finally:
                try:
                    os.unlink(path)
                except OSError:
                    pass
        audio = audio_int16.flatten().astype(np.float32) / 32768.0
        segments, _ = self.model.transcribe(
            audio, beam_size=1, language=config.WHISPER_LANG, vad_filter=True
        )
        return "".join(s.text for s in segments).strip()

    def transcribe_int16_wake_biased(self, audio_int16: np.ndarray) -> str:
        """Retry idle audio with wake-word-friendly STT settings.

        Used only before the wake gate. It fixes short "Leha" clips that
        Deepgram auto-language detection misreads as unrelated words.
        """
        if self.engine != "deepgram" or not config.DEEPGRAM_API_KEY:
            return ""
        import soundfile as sf
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
            path = f.name
        try:
            sf.write(path, audio_int16, config.SAMPLE_RATE)
            return self._deepgram(path, wake_bias=True)
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def transcribe_int16_sarvam(self, audio_int16: np.ndarray) -> str:
        """Independently verify an ambiguous short wake transcript."""
        if not getattr(config, "SARVAM_API_KEY", ""):
            return ""
        import soundfile as sf
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
            path = f.name
        try:
            sf.write(path, audio_int16, config.SAMPLE_RATE)
            return self._sarvam(path)
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def transcribe_int16_wake_candidates(self, audio_int16: np.ndarray) -> str:
        """Run independent strict wake STT providers concurrently.

        The first transcript that passes the strict Leha gate wins. If neither
        confirms the wake word, return one transcript for normal diagnostics;
        AssistantSession will ignore it and no action can run.
        """
        from .wake_phrases import has_trigger

        providers = []
        if self.engine == "deepgram" and config.DEEPGRAM_API_KEY:
            providers.append("deepgram")
        if getattr(config, "SARVAM_API_KEY", ""):
            providers.append("sarvam")
        if not providers:
            return self.transcribe_int16(audio_int16, rescue_indian=False)

        def transcribe(provider: str) -> str:
            import soundfile as sf

            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
                path = f.name
            try:
                sf.write(path, audio_int16, config.SAMPLE_RATE)
                if provider == "deepgram":
                    return self._deepgram(path, wake_bias=True).strip()
                return self._sarvam(path).strip()
            finally:
                try:
                    os.unlink(path)
                except OSError:
                    pass

        executor = ThreadPoolExecutor(max_workers=len(providers), thread_name_prefix="wake-stt")
        futures = [executor.submit(transcribe, provider) for provider in providers]
        fallback = ""
        try:
            for future in as_completed(futures):
                try:
                    text = future.result()
                except Exception:
                    text = ""
                if text and not fallback:
                    fallback = text
                if text and has_trigger(text):
                    return text
            return fallback
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def transcribe_int16_command_candidates(self, audio_int16: np.ndarray) -> str:
        """Choose the strongest command transcript from Deepgram and Sarvam."""
        from .wake_phrases import is_hallucination

        providers = []
        if config.DEEPGRAM_API_KEY:
            providers.append("deepgram")
        if getattr(config, "SARVAM_API_KEY", ""):
            providers.append("sarvam")
        if len(providers) < 2:
            return self.transcribe_int16(audio_int16, rescue_indian=True)

        def transcribe(provider: str) -> tuple[str, str]:
            import soundfile as sf

            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
                path = f.name
            try:
                sf.write(path, audio_int16, config.SAMPLE_RATE)
                text = self._deepgram(path) if provider == "deepgram" else self._sarvam(path)
                return provider, text.strip()
            finally:
                try:
                    os.unlink(path)
                except OSError:
                    pass

        results = {}
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="command-stt") as executor:
            for provider, text in executor.map(transcribe, providers):
                if text:
                    results[provider] = text
        if not results:
            return ""

        def quality(item: tuple[str, str]) -> tuple[float, int]:
            provider, text = item
            words = len(text.split())
            score = float(min(words, 12))
            if is_hallucination(text):
                score -= 8.0
            if _has_indic_script(text):
                score += 5.0
            if provider == "sarvam":
                score += 1.5
            return score, words

        selected_provider, selected_text = max(results.items(), key=quality)
        summary = " ".join(
            f"{provider}='{text[:70]}'" for provider, text in results.items()
        )
        print(
            f"[ears] command candidates: {summary}; selected={selected_provider}",
            flush=True,
        )
        return selected_text
