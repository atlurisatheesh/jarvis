"""Speech-to-text with Deepgram, OpenAI, Groq, and local Whisper providers."""
import os
import tempfile

import numpy as np

from . import config

_GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
_OPENAI_URL = "https://api.openai.com/v1/audio/transcriptions"
_DEEPGRAM_URL = "https://api.deepgram.com/v1/listen"


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
        else:
            if requested != "local":
                print(f"[ears] {requested} is not configured -> falling back to local Whisper")
            self._ensure_local()

    @staticmethod
    def _select_engine(requested: str) -> str:
        requested = (requested or "auto").lower()
        available = {
            "deepgram": bool(config.DEEPGRAM_API_KEY),
            "openai": bool(config.OPENAI_API_KEY),
            "groq": bool(config.GROQ_API_KEY),
        }
        if requested == "auto":
            for name in ("deepgram", "openai", "groq"):
                if available[name]:
                    return name
            return "local"
        if requested in available and available[requested]:
            return requested
        return "local"

    def _provider_candidates(self, primary: str) -> list[str]:
        providers = ["deepgram", "openai", "groq"]
        available = {
            "deepgram": bool(config.DEEPGRAM_API_KEY),
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

    def _deepgram(self, path: str) -> str:
        import requests
        params = {
            "model": config.DEEPGRAM_STT_MODEL,
            "smart_format": "true",
            "punctuate": "true",
        }
        if config.WHISPER_LANG:
            params["language"] = config.WHISPER_LANG
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
                    timeout=config.STT_REQUEST_TIMEOUT_SECONDS,
                )
            if not r.ok:
                print(f"[ears] Deepgram error {r.status_code}: {r.text[:160]}")
                if r.status_code in {401, 403}:
                    self._disable_provider("deepgram")
                return ""
            channels = r.json().get("results", {}).get("channels", [])
            alternatives = channels[0].get("alternatives", []) if channels else []
            return (alternatives[0].get("transcript") or "").strip() if alternatives else ""
        except Exception as e:
            print(f"[ears] Deepgram error: {e}")
            return ""

    # ---- local ----
    def _local_file(self, path: str) -> str:
        segments, _ = self.model.transcribe(
            path, beam_size=1, language=config.WHISPER_LANG, vad_filter=True
        )
        return "".join(s.text for s in segments).strip()

    # ---- public API ----
    def transcribe_file(self, path: str) -> str:
        providers = list(self._provider_order)
        for provider in providers:
            if provider == "deepgram":
                text = self._deepgram(path)
            elif provider == "openai":
                text = self._openai(path)
            else:
                text = self._groq(path)
            if text:
                if provider != self.engine:
                    print(f"[ears] switching STT fallback to {provider}")
                    self.engine = provider
                    self._provider_order = self._provider_candidates(provider)
                return text
        if self.engine != "local" and config.STT_CLOUD_FALLBACK_TO_LOCAL:
            print("[ears] cloud transcription unavailable -> local Whisper fallback")
            self._ensure_local()
            return self._local_file(path)
        return self._local_file(path) if self.engine == "local" else ""

    def transcribe_int16(self, audio_int16: np.ndarray) -> str:
        """Transcribe a raw int16 mono buffer (16 kHz) from the mic."""
        if self.engine != "local":
            import soundfile as sf
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
                path = f.name
            try:
                sf.write(path, audio_int16, config.SAMPLE_RATE)
                return self.transcribe_file(path)
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
