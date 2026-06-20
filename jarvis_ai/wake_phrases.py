"""Shared wake-word and STT-noise helpers for Leha.

Whisper doesn't know "Leha" — it's not in its training data. So we use:
  1. A large set of known Whisper manglings as exact triggers
  2. A phonetic similarity function that catches NEW manglings automatically
  3. Heavy Whisper prompt bias in ears.py to steer toward "Leha"
"""
import string
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
}

# ── Exact / known Whisper manglings of "Leha" ──────────────────────
TRIGGERS = (
    # exact / greetings
    "hey leha", "hi leha", "ok leha", "okay leha", "hello leha",
    # core variants
    "leha", "leah", "lea", "liha", "leeha", "layha", "laiha",
    "le ha", "lee ha", "lia", "liya", "laya", "leyah", "leya",
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
    "lehaa", "leia", "liah", "lihaa", "leaha", "lehha",
    "lena", "lela", "leela", "lelaa", "layla", "lela",
    "hey leah", "hey leia", "ok leah", "okay leah",
)

# Short fragments for substring matching
_TRIGGER_FRAGMENTS = (
    "leha", "leah", "leeha", "liha", "leya", "liya", "lehah", "leyha",
    "lehaa", "leia", "lihaa",
    "lena", "lela", "leela", "layla",
)

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
    if word.startswith(("leh", "lee", "lea", "ley", "lih", "liy", "lay", "lai")):
        return True
    # Edit-distance fallback for Whisper near-misses: lena, lela, lehae, etc.
    if max(SequenceMatcher(None, word, target).ratio() for target in ("leha", "leah", "leeha")) >= 0.72:
        return True
    # Soundex match — "Leha" has soundex L000
    sx = _soundex_simple(word)
    if sx in ("L000", "L200"):  # L000 = leha/leah, L200 = lexa/lesa
        return True
    return False


def wake_confidence(text: str) -> float:
    """Return a rough 0..1 wake confidence for diagnostics."""
    low = normalize_text(text)
    if any(t in low for t in TRIGGERS):
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
    if len(words) <= 2 and not any(t in low for t in _TRIGGER_FRAGMENTS):
        if len(low) < 5:
            return True

    return False


def has_trigger(text: str) -> bool:
    """Check if text contains a fuzzy wake-word match for 'Leha'."""
    low = normalize_text(text)
    # Check exact triggers first (fast path)
    if any(t in low for t in TRIGGERS):
        return True
    # Check each word phonetically (catches new/unseen manglings)
    return wake_confidence(low) >= 0.72


def strip_trigger(text: str) -> str:
    """Remove a leading wake phrase from text, return the command portion."""
    low = normalize_text(text)
    # Try longest triggers first to avoid partial matches
    for trigger in sorted(TRIGGERS, key=len, reverse=True):
        if low.startswith(trigger):
            return low[len(trigger):].strip(" ,.")
    # Try phonetic match on first word
    words = low.split()
    if words and _looks_like_leha(words[0]):
        return " ".join(words[1:]).strip()
    return low
