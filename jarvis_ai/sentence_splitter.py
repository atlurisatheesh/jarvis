"""Safe sentence splitter for streaming TTS.

Splits text into chunks at sentence boundaries for natural-sounding
streaming speech.  Handles abbreviations, list items, and avoids
mid-word cuts.
"""
from __future__ import annotations

import re


# Common abbreviations that should NOT trigger a sentence break.
_ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "ave", "blvd",
    "inc", "ltd", "co", "corp", "vs", "etc", "approx", "no",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "oct", "nov", "dec",
    "mon", "tue", "wed", "thu", "fri", "sat", "sun",
    "a.m", "p.m", "u.s", "u.k", "e.g", "i.e",
}


def split_sentences(text: str) -> list[str]:
    """Split text into sentence chunks for streaming TTS.

    Returns a list of non-empty sentence strings (with trailing punctuation).
    Handles:
        - Periods after abbreviations (Mr., Dr., etc.)
        - Question marks and exclamation points
        - List items ("1. ", "a. ", "- ")
        - Newlines
        - Very long sentences (split at comma/semicolon if > 40 words)
    """
    if not text or not text.strip():
        return []

    sentences: list[str] = []
    current: list[str] = []

    # First split on newlines and list markers
    lines = re.split(r"\n+", text.strip())
    for line in lines:
        line = line.strip()
        if not line:
            continue
        _split_line(line, sentences)

    # Now split any overly long sentences at clause boundaries
    result: list[str] = []
    for sent in sentences:
        result.extend(_split_long_sentence(sent))

    return [s.strip() for s in result if s.strip()]


def _split_line(line: str, out: list[str]):
    """Split a single line into sentences, respecting abbreviations."""
    tokens = re.findall(r"[^.!?]+[.!?]?", line)
    buf = ""
    for token in tokens:
        buf += token
        # Check if this token ends a sentence
        stripped = buf.rstrip()
        if stripped and stripped[-1] in ".!?":
            # Check for abbreviation before the period
            word_before = re.split(r"[\s,]+", stripped.rstrip(".!?").strip())[-1].lower()
            if word_before in _ABBREVIATIONS:
                continue  # not a real sentence end
            out.append(stripped)
            buf = ""
    if buf.strip():
        out.append(buf.strip())


def _split_long_sentence(sentence: str, max_words: int = 40) -> list[str]:
    """Split a very long sentence at clause boundaries (comma/semicolon)."""
    words = sentence.split()
    if len(words) <= max_words:
        return [sentence]

    # Try splitting at commas/semicolons first
    parts = re.split(r"([,;:])", sentence)
    chunks: list[str] = []
    current_words: list[str] = []
    current_count = 0

    i = 0
    while i < len(parts):
        part = parts[i]
        if part in (",", ";", ":"):
            current_words.append(part)
            i += 1
            continue
        word_count = len(part.split())
        if current_count + word_count > max_words and current_words:
            chunks.append(" ".join(current_words).strip())
            current_words = []
            current_count = 0
        current_words.append(part)
        current_count += word_count
        i += 1

    if current_words:
        chunks.append(" ".join(current_words).strip())

    return [c for c in chunks if c.strip()]


def split_for_tts(text: str, min_chunk_chars: int = 30) -> list[str]:
    """Split text into TTS-friendly chunks.

    Unlike ``split_sentences``, this may combine short sentences into a
    single chunk for efficiency, or split long sentences further.
    """
    sentences = split_sentences(text)
    if not sentences:
        return []

    chunks: list[str] = []
    current = ""

    for sent in sentences:
        candidate = f"{current} {sent}".strip() if current else sent
        if len(candidate) >= min_chunk_chars:
            chunks.append(candidate)
            current = ""
        else:
            current = candidate

    if current:
        chunks.append(current)

    return chunks
