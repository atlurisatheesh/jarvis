"""Phase 8: local conversation summarizer.

Compresses a long conversation into compact, reviewable notes **without sending
the full history to a cloud model**. The default path is purely local and
extractive (no deps, always available offline):

* split into turns,
* score sentences by keyword salience (term frequency minus stopwords),
* keep the top sentences in original order, capped to a length budget.

An optional ``use_brain=True`` path can hand the already-shortened extract to the
local Ollama brain for a cleaner abstractive note, but it is opt-in so the
summarizer never blocks or leaks history by default.
"""
from __future__ import annotations

import re

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "is", "are", "was", "were", "to", "of",
    "in", "on", "for", "with", "as", "at", "by", "it", "this", "that", "i", "you",
    "he", "she", "they", "we", "me", "my", "your", "so", "do", "did", "have", "has",
    "be", "will", "would", "can", "could", "what", "how", "okay", "ok", "yes", "no",
}

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _sentences(text: str) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    parts = [s.strip() for s in _SENT_SPLIT.split(text) if s.strip()]
    return parts


def _score(sentence: str, freqs: dict[str, int]) -> float:
    words = re.findall(r"[a-z']+", sentence.lower())
    if not words:
        return 0.0
    return sum(freqs.get(w, 0) for w in words) / len(words)


def summarize(text: str, max_sentences: int = 3) -> str:
    """Extractive local summary. Deterministic, offline, no deps."""
    sentences = _sentences(text)
    if len(sentences) <= max_sentences:
        return " ".join(sentences)
    freqs: dict[str, int] = {}
    for w in re.findall(r"[a-z']+", text.lower()):
        if w in _STOPWORDS or len(w) < 3:
            continue
        freqs[w] = freqs.get(w, 0) + 1
    ranked = sorted(range(len(sentences)),
                    key=lambda i: _score(sentences[i], freqs), reverse=True)
    keep = sorted(ranked[:max_sentences])
    return " ".join(sentences[i] for i in keep)


def summarize_turns(turns: list[dict], max_sentences: int = 4) -> str:
    """Summarize a list of {role, text} turns into a compact note.

    Only the text content is used; roles are folded in as light prefixes so the
    summary stays readable. Falls back to the joined text when short.
    """
    blocks = []
    for t in turns or []:
        role = (t.get("role") or "").strip().lower()
        content = (t.get("text") or t.get("content") or "").strip()
        if not content:
            continue
        prefix = "User: " if role in ("user", "owner") else ("Leha: " if role else "")
        blocks.append(prefix + content)
    joined = " ".join(blocks)
    return summarize(joined, max_sentences=max_sentences)


def summarize_with_brain(text: str, max_sentences: int = 3) -> str:
    """Opt-in abstractive pass: shorten locally first, then ask the local brain.

    Never sends raw full history — only the already-extracted summary. Falls
    back to the extractive result on any error.
    """
    extract = summarize(text, max_sentences=max_sentences)
    try:
        from . import brain  # local Ollama path
        prompt = (
            "Rewrite these notes as one or two short, neutral sentences a user "
            "could review later. Do not add information.\n\n" + extract
        )
        out = brain.Brain().ask(prompt)
        return (out or extract).strip()
    except Exception:
        return extract
