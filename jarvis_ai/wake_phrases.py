"""Shared wake-word and STT-noise helpers for Leha.

Whisper doesn't know "Leha" — it's not in its training data. So we use:
  1. A large set of known Whisper manglings as exact triggers
  2. A phonetic similarity function that catches NEW manglings automatically
  3. Heavy Whisper prompt bias in ears.py to steer toward "Leha"

When the dedicated ONNX Leha wake detector (:data:`config.CUSTOM_WAKE_ENABLED`)
is the *primary* wake engine, transcript matching is only a fallback. In that
case :func:`strict_mode` is True and :func:`has_trigger` drops the broad,
aggressive fuzzy aliases (like "lena", "layla", soundex L200) that are prone
to false wakes. The high-precision triggers and the strongest phonetic match
remain so the transcript fallback still catches clear "Leha" speech.
"""
import os
import string
import re
from difflib import SequenceMatcher

# ── Whisper hallucination patterns ──────────────────────────────────
NOISE_PHRASES = {
    "", ".", "you", "so", "the", "okay", "bye", "yeah", "yes", "no", "oh",
    "hmm", "huh", "uh", "um", "ah", "nice", "book", "yess", "guys",
    "thank you", "thanks", "thanks for watching", "thanks for watching!",
    "bye bye", "okay.",
    "i'm sorry", "sorry",
    "please subscribe", "subscribe",
    "see you next time", "thanks for listening",
    "like and subscribe",
    "you're welcome",
    "good night",
    "hello", "hi",
    "take care",
    "go ahead", "go ahead mike", "go ahead mic", "go head mike",
}

INDIC_WAKE_TRIGGERS = (
    "लेहा", "लेखा", "लीहा",
    "లేహా", "లేఖ", "లీహా",
    "லேஹா", "லேகா", "லீஹா",
    "ಲೇಹಾ", "ಲೇಖಾ", "ಲೀಹಾ",
    "ലേഹ", "ലേഖ", "ലീഹ",
    "লেহা", "লেখা", "লীহা",
    "લેહા", "લેખા", "લીહા",
)

# Exact strict-mode variants observed from this laptop microphone. Keep this
# intentionally tiny; broad aliases such as layer/later still cause false wakes.
OBSERVED_STRICT_WAKE_TRIGGERS = (
    "lehon",
    "lehav",
)

# ── Exact / known Whisper manglings of "Leha" ──────────────────────
TRIGGERS = (
    # exact / greetings
    "hey leha", "hi leha", "ok leha", "okay leha", "hello leha",
    # openWakeWord "hey jarvis" trigger (used when OWW is the primary engine)
    "hey jarvis", "hi jarvis", "ok jarvis", "okay jarvis", "hello jarvis",
    "jarvis",
    # core variants
    "leha", "leah", "liha", "leeha", "layha", "laiha", "lehav", "lehra",
    "leja", "lekha", "lleha",
    "le ha", "lee ha", "lia", "liya", "laya", "leyah", "leya",
    # Real room/STT misses seen in live logs
    "layer", "lair", "lear", "lehr", "lehrer", "later",
    # Whisper manglings observed in real sessions
    "jai maaise", "ja reis", "ja razi", "jaros",
    "jai royce", "ciao royce",
    "c est la vie",   # Whisper sometimes hears this
    "yeah luis",
    "yessir guys",    # observed mangling
    # more phonetic variants Whisper might produce
    "lehah", "lehha", "lehe", "laha", "lahe",
    "leyha", "leaha", "leeah", "leea",
    "le hah", "lay ha", "lee hah",
    "lehaa", "leia", "liah", "lihaa", "leaha", "lehha", "levah", "lerha",
    "leja", "lekha", "lleha",
    "lena", "lela", "leela", "lelaa", "layla", "lela",
    "hey leah", "hey leia", "ok leah", "okay leah",
) + INDIC_WAKE_TRIGGERS

# Short fragments for substring matching
_TRIGGER_FRAGMENTS = (
    "leha", "leah", "leeha", "liha", "leya", "liya", "lehah", "leyha",
    "lehaa", "leia", "lihaa", "lehav", "levah", "lehra", "lerha",
    "leja", "lekha", "lleha",
    "layer", "lair", "lear", "lehr", "lehrer", "later",
    "lena", "lela", "leela", "layla",
) + INDIC_WAKE_TRIGGERS

# High-precision triggers used in strict mode (dedicated ONNX model is primary).
# Only the clearest, lowest-false-positive variants are kept. Broad near-misses
# like "lena"/"layla"/"leela" are dropped because the ONNX detector now handles
# real wake detection and these only add false triggers in transcript fallback.
_STRICT_TRIGGERS = (
    "hey leha", "hi leha", "ok leha", "okay leha", "hello leha",
    "leha", "leah", "liha", "leeha",
    "lehah", "lehha", "lehaa", "lehe", "leia", "leja", "lekha", "lleha",
    "hey leah", "ok leah", "okay leah",
    "hey jarvis", "hi jarvis", "jarvis",
    *OBSERVED_STRICT_WAKE_TRIGGERS,
    *INDIC_WAKE_TRIGGERS,
)

_STRICT_FRAGMENTS = (
    "leha", "leah", "leeha", "liha", "lehah", "lehaa", "leia", "leja", "lekha", "lleha",
    *OBSERVED_STRICT_WAKE_TRIGGERS,
    *INDIC_WAKE_TRIGGERS,
)


def strict_mode() -> bool:
    """Return strict/high-precision transcript wake aliases."""
    try:
        from . import config
        raw = getattr(config, "TRANSCRIPT_WAKE_STRICT", True)
        if raw is True or raw is False:
            return raw
        if isinstance(raw, str) and raw.lower() in ("0", "false", "no", "off"):
            return False
        if isinstance(raw, str) and raw.lower() in ("1", "true", "yes", "on"):
            return True
        # auto — only strict when the dedicated model is actually running
        return True
    except Exception:
        return True


# Precise variants only — no broad near-misses like "layla"/"lena"/"leela".
_PRECISE_VARIANTS = {
    "leha", "leah", "liha", "leeha", "lehah", "lehha", "lehaa", "lehe",
    "leia", "leja", "lekha", "lleha",
    *OBSERVED_STRICT_WAKE_TRIGGERS,
    *INDIC_WAKE_TRIGGERS,
}


def _looks_like_leha_strict(word: str) -> bool:
    """High-precision phonetic check used when the ONNX model is primary.

    Only accepts the clearest "Leha" pronunciations and very close spellings,
    dropping broad distractors (layla, lena, leela) that add false wakes.
    """
    word = word.strip().lower()
    if word in _PRECISE_VARIANTS:
        return True
    if len(word) < 4 or len(word) > 6:
        return False
    # Only the strongest similarity to the exact phonemes.
    return max(
        SequenceMatcher(None, word, t).ratio() for t in ("leha", "leah", "leeha")
    ) >= 0.93


def _contains_trigger_phrase(low: str, triggers) -> bool:
    """Match wake phrases on word boundaries, not inside unrelated words."""
    for trigger in triggers:
        pattern = r"(?<![a-z0-9])" + re.escape(trigger) + r"(?![a-z0-9])"
        if re.search(pattern, low):
            return True
    return False


def _strip_leading_trigger_phrase(low: str, triggers) -> str | None:
    """Remove a leading wake phrase only when it ends on a word boundary."""
    for trigger in sorted(triggers, key=len, reverse=True):
        pattern = r"^" + re.escape(trigger) + r"(?![a-z0-9])\s*"
        if re.match(pattern, low):
            return re.sub(pattern, "", low, count=1).strip(" ,.")
    return None

# ── Phonetic similarity for unknown manglings ──────────────────────

def _soundex_simple(word: str) -> str:
    """Very simple soundex-like hash to catch phonetic variants of 'Leha'."""
    if not word:
        return ""
    # Map consonants to codes, vowels to 0
    codes = {
        'b': '1', 'f': '1', 'p': '1', 'v': '1',
        'c': '2', 'g': '2', 'j': '2', 'k': '2', 'q': '2', 's': '2', 'x': '2', 'z': '2',
        'd': '3', 't': '3',
        'l': '4',
        'm': '5', 'n': '5',
        'r': '6',
    }
    first = word[0].upper()
    out = [first]
    prev = codes.get(word[0].lower(), '0')
    for c in word[1:]:
        code = codes.get(c, '0')
        if code != '0' and code != prev:
            out.append(code)
        prev = code if code != '0' else prev
    return ''.join(out)[:4].ljust(4, '0')


def _looks_like_leha(word: str) -> bool:
    """Catch STT variants phonetically similar to 'Leha'."""
    word = word.strip().lower()
    if len(word) < 3 or len(word) > 8:
        return False
    # Direct prefix check — catches leha, leah, lehah, leeha, etc.
    if word in {
        "leha", "leah", "liha", "leeha", "layha", "laiha", "liya",
        "laya", "leyah", "leya", "lehah", "lehha", "lehe", "lehav", "levah", "lehra", "lerha", "laha",
        "lahe", "leyha", "leaha", "leeah", "leea", "lehaa", "leia",
        "leja", "lekha", "lleha",
        "layer", "lair", "lear", "lehr", "lehrer", "later",
        "liah", "lihaa", "lena", "lela", "leela", "layla",
    }:
        return True
    # Edit-distance fallback for Whisper near-misses: lena, lela, lehae, etc.
    if max(SequenceMatcher(None, word, target).ratio() for target in ("leha", "leah", "leeha")) >= 0.86:
        return True
    # Soundex match — "Leha" has soundex L000
    sx = _soundex_simple(word)
    if sx in ("L000", "L200"):  # L000 = leha/leah, L200 = lexa/lesa
        return True
    return False


def wake_confidence(text: str) -> float:
    """Return a rough 0..1 wake confidence for diagnostics."""
    low = normalize_text(text)
    if _contains_trigger_phrase(low, TRIGGERS):
        return 1.0
    scores = []
    words = low.split()
    for word in words:
        if _looks_like_leha(word):
            scores.append(0.82)
        scores.extend(SequenceMatcher(None, word, target).ratio() for target in ("leha", "leah", "leeha"))
    for i in range(len(words) - 1):
        pair = words[i] + words[i + 1]
        scores.extend(SequenceMatcher(None, pair, target).ratio() for target in ("leha", "leeha"))
    return max(scores, default=0.0)


def normalize_text(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    table = str.maketrans({c: " " for c in string.punctuation})
    return " ".join((text or "").lower().translate(table).split())


def is_hallucination(text: str) -> bool:
    """Detect common Whisper silence/noise hallucinations."""
    low = normalize_text(text)
    if low in NOISE_PHRASES:
        return True

    words = low.split()
    # Repetitive phrases (e.g. "I'm sorry. I'm sorry.")
    if len(words) >= 4:
        for phrase_len in range(1, min(4, len(words) // 2 + 1)):
            phrase = tuple(words[:phrase_len])
            chunks = [
                tuple(words[i:i + phrase_len])
                for i in range(0, len(words), phrase_len)
            ]
            if all(c == phrase for c in chunks if len(c) == phrase_len):
                return True

    # Dots/periods only
    if text and all(c in ". " for c in text):
        return True

    # Very short non-trigger text
    fragments = _STRICT_FRAGMENTS if strict_mode() else _TRIGGER_FRAGMENTS
    if len(words) <= 2 and not any(t in low for t in fragments):
        if len(low) < 5:
            return True

    return False


def has_trigger(text: str) -> bool:
    """Check if text contains a fuzzy wake-word match for 'Leha'.

    When :func:`strict_mode` is active (dedicated ONNX detector is primary),
    only high-precision triggers and a stricter phonetic threshold are used so
    the transcript fallback does not introduce false wakes.
    """
    low = normalize_text(text)
    if strict_mode():
        if _contains_trigger_phrase(low, _STRICT_TRIGGERS):
            return True
        # High-precision phonetic fallback only — no broad aliases.
        words = low.split()
        return any(_looks_like_leha_strict(w) for w in words[:2])
    # Check exact triggers first (fast path)
    if _contains_trigger_phrase(low, TRIGGERS):
        return True
    # Check each word phonetically (catches new/unseen manglings)
    return wake_confidence(low) >= 0.82


def strip_trigger(text: str) -> str:
    """Remove a leading wake phrase from text, return the command portion."""
    low = normalize_text(text)
    # Try longest triggers first to avoid partial matches, but only at word
    # boundaries so "learn" is not stripped by the "lear" wake alias.
    leading_triggers = _STRICT_TRIGGERS if strict_mode() else TRIGGERS
    stripped = _strip_leading_trigger_phrase(low, leading_triggers)
    if stripped is not None:
        return stripped
    # Try phonetic match on first word
    words = low.split()
    if words and _looks_like_leha(words[0]):
        return " ".join(words[1:]).strip()
    return low
