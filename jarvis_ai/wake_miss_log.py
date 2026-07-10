"""Missed wake-word evidence log.

The custom neural wake model is intentionally disabled until it passes eval.
This module improves the safer transcript wake path by recording ignored
utterances and summarising likely Leha variants from real room audio.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Iterable

from . import config
from .wake_phrases import normalize_text, wake_confidence


_BLOCKED_CANDIDATES = {
    "a", "an", "and", "are", "hello", "hi", "yeah", "yes", "no", "ok", "okay",
    "layer", "later", "layla", "lena", "leela", "lela", "lear", "lair",
    "lehr", "lehra", "leader", "letter",
}


def _log_path() -> Path | None:
    raw = getattr(config, "WAKE_MISS_LOG", "").strip()
    if not raw:
        return None
    return Path(raw)


def log_miss(text: str, confidence: float | None = None, *, reason: str = "no wake trigger", source: str = "listener") -> None:
    """Append one ignored transcript to the wake miss log.

    Logging is best-effort. It must never break the live voice loop.
    """
    text = (text or "").strip()
    if not text:
        return
    path = _log_path()
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        item = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "text": text[:500],
            "normalized": normalize_text(text)[:500],
            "confidence": float(wake_confidence(text) if confidence is None else confidence),
            "reason": reason,
            "source": source,
        }
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(item, ensure_ascii=True) + "\n")
    except Exception:
        return


def load_recent(limit: int = 2000) -> list[dict]:
    path = _log_path()
    if path is None or not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []
    out: list[dict] = []
    for line in lines[-max(1, int(limit)):]:
        try:
            item = json.loads(line)
        except Exception:
            continue
        if isinstance(item, dict):
            out.append(item)
    return out


def _candidate_prefixes(normalized: str) -> Iterable[str]:
    words = re.findall(r"[a-z0-9]+", normalized.lower())
    if not words:
        return []
    candidates = [words[0]]
    if len(words) > 1:
        candidates.append(words[0] + " " + words[1])
    return candidates


def suggest_variants(*, min_confidence: float = 0.58, min_count: int = 2, limit: int = 10) -> list[dict]:
    """Return conservative wake-variant candidates from recent misses."""
    counts: Counter[str] = Counter()
    max_conf: dict[str, float] = defaultdict(float)
    examples: dict[str, list[str]] = defaultdict(list)

    for item in load_recent():
        normalized = str(item.get("normalized") or normalize_text(str(item.get("text", ""))))
        text = str(item.get("text", "")).strip()
        conf = float(item.get("confidence") or wake_confidence(normalized))
        for cand in _candidate_prefixes(normalized):
            if cand in _BLOCKED_CANDIDATES:
                continue
            compact = cand.replace(" ", "")
            if len(compact) < 3 or len(compact) > 12:
                continue
            cand_conf = max(conf, wake_confidence(cand))
            if cand_conf < min_confidence:
                continue
            counts[cand] += 1
            max_conf[cand] = max(max_conf[cand], cand_conf)
            if text and len(examples[cand]) < 3:
                examples[cand].append(text)

    rows = [
        {
            "candidate": cand,
            "count": count,
            "max_confidence": round(max_conf[cand], 3),
            "examples": examples[cand],
        }
        for cand, count in counts.items()
        if count >= min_count
    ]
    rows.sort(key=lambda r: (r["count"], r["max_confidence"]), reverse=True)
    return rows[: max(1, int(limit))]


def status() -> dict:
    items = load_recent()
    return {
        "path": str(_log_path() or ""),
        "miss_count": len(items),
        "suggestions": suggest_variants(),
        "note": "Only add a suggested variant after checking examples for false wakes.",
    }


def spoken_status() -> str:
    data = status()
    suggestions = data["suggestions"]
    if not suggestions:
        return f"I have {data['miss_count']} wake misses logged, but no safe new wake variant yet."
    top = suggestions[0]
    return (
        f"I have {data['miss_count']} wake misses logged. "
        f"Top possible variant is {top['candidate']}, seen {top['count']} times. "
        "Review it before adding it."
    )
