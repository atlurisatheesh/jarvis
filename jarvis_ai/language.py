"""Lightweight language helpers for multilingual voice replies."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LanguageProfile:
    code: str
    name: str
    edge_voice: str


_SCRIPT_RANGES: list[tuple[str, str, str, str]] = [
    ("\u0900", "\u097f", "hi", "Hindi", "hi-IN-SwaraNeural"),
    ("\u0980", "\u09ff", "bn", "Bengali", "bn-IN-TanishaaNeural"),
    ("\u0a80", "\u0aff", "gu", "Gujarati", "gu-IN-DhwaniNeural"),
    ("\u0b00", "\u0b7f", "or", "Odia", "or-IN-SubhasiniNeural"),
    ("\u0b80", "\u0bff", "ta", "Tamil", "ta-IN-PallaviNeural"),
    ("\u0c00", "\u0c7f", "te", "Telugu", "te-IN-ShrutiNeural"),
    ("\u0c80", "\u0cff", "kn", "Kannada", "kn-IN-SapnaNeural"),
    ("\u0d00", "\u0d7f", "ml", "Malayalam", "ml-IN-SobhanaNeural"),
]

_KEYWORD_PROFILES = {
    "hindi": LanguageProfile("hi", "Hindi", "hi-IN-SwaraNeural"),
    "telugu": LanguageProfile("te", "Telugu", "te-IN-ShrutiNeural"),
    "tamil": LanguageProfile("ta", "Tamil", "ta-IN-PallaviNeural"),
    "kannada": LanguageProfile("kn", "Kannada", "kn-IN-SapnaNeural"),
    "malayalam": LanguageProfile("ml", "Malayalam", "ml-IN-SobhanaNeural"),
    "marathi": LanguageProfile("mr", "Marathi", "mr-IN-AarohiNeural"),
    "gujarati": LanguageProfile("gu", "Gujarati", "gu-IN-DhwaniNeural"),
    "bengali": LanguageProfile("bn", "Bengali", "bn-IN-TanishaaNeural"),
    "odia": LanguageProfile("or", "Odia", "or-IN-SubhasiniNeural"),
}

DEFAULT_PROFILE = LanguageProfile("en-IN", "Indian English", "en-IN-NeerjaNeural")

_ROMANIZED_PROFILES: list[tuple[set[str], LanguageProfile]] = [
    ({
        "nenu", "nannu", "naku", "naaku", "nuvvu", "meeru", "meeku",
        "enti", "emiti", "ante", "antey", "cheppu", "cheppandi",
        "ela", "ekkada", "ikkada", "ledu", "undi", "kavali", "kaavali",
        "bagundi", "baagundi", "chala", "chaala", "telugu", "ra", "raa",
        "amma", "nanna", "anna", "akka", "tammudu", "chelli",
    }, _KEYWORD_PROFILES["telugu"]),
    ({
        "hai", "kya", "kyun", "kaise", "kaisa", "kaisi", "mujhe", "mujhko",
        "tum", "aap", "mera", "meri", "mere", "nahi", "nahin", "haan",
        "achha", "accha", "batao", "bolo", "hindi",
    }, _KEYWORD_PROFILES["hindi"]),
    ({
        "enna", "epdi", "eppadi", "enga", "inge", "illa", "irukku",
        "venum", "sollu", "sollunga", "romba", "tamil",
    }, _KEYWORD_PROFILES["tamil"]),
    ({
        "enu", "yenu", "hege", "elli", "illa", "ide", "beku",
        "helu", "kannada",
    }, _KEYWORD_PROFILES["kannada"]),
]


def _words(text: str) -> set[str]:
    return {
        token.strip(".,!?;:'\"()[]{}").lower()
        for token in (text or "").split()
        if token.strip(".,!?;:'\"()[]{}")
    }


def detect_language(text: str) -> LanguageProfile:
    """Best-effort local language detection.

    This is intentionally cheap: script detection for native Indian scripts and
    keyword detection for spoken/typed commands like "reply in Telugu".
    """
    raw = text or ""
    low = raw.lower()
    for keyword, profile in _KEYWORD_PROFILES.items():
        if keyword in low:
            return profile
    for ch in raw:
        for start, end, code, name, voice in _SCRIPT_RANGES:
            if start <= ch <= end:
                return LanguageProfile(code, name, voice)
    words = _words(raw)
    for keywords, profile in _ROMANIZED_PROFILES:
        if len(words & keywords) >= 1:
            return profile
    return DEFAULT_PROFILE


def is_indian_language(text: str) -> bool:
    return detect_language(text).code != "en-IN"


def is_romanized_indian_language(text: str) -> bool:
    raw = text or ""
    profile = detect_language(raw)
    if profile.code == "en-IN":
        return False
    for ch in raw:
        for start, end, *_ in _SCRIPT_RANGES:
            if start <= ch <= end:
                return False
    return True


def edge_voice_for_text(text: str) -> str:
    return detect_language(text).edge_voice


def prompt_language_rule() -> str:
    return (
        "Language rule: understand English, Hinglish, Hindi, Telugu, Tamil, "
        "Kannada, Malayalam, Marathi, Gujarati, Bengali, and mixed Indian "
        "speech. Reply in the same language/script the user used. If the user "
        "mixes English with an Indian language, reply naturally in that mixed "
        "style. If the user speaks an Indian language using English letters "
        "(for example romanized Telugu like 'nannu antey'), answer in that "
        "language's native script for clearer speech unless they explicitly ask "
        "for English letters. Keep voice answers short."
    )
