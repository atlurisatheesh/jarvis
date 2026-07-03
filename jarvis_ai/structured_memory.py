"""Phase 8: structured personal memory.

The existing ``memory.py`` keeps a flat list of fact strings. This module adds a
typed store with separate buckets so recall and deletion are precise, without
disturbing the old flat store (which stays for backward compatibility).

Buckets (``MemoryType``):

* ``fact``         — durable facts ("my car is a blue Swift")
* ``preference``   — how the user likes things ("brief answers", "celsius")
* ``task``         — task history / things to do
* ``contact_note`` — notes tied to a person

Each entry: ``{id, type, text, key, created_at}``. ``key`` is an optional short
handle for direct lookup/overwrite (e.g. preference "units" -> "celsius").

Pure JSON, offline, zero extra deps. Used by the memory skills
(``remember_this`` / ``what_do_you_remember`` / ``forget_that``).
"""
from __future__ import annotations

import json
import threading
import time
import uuid

from . import config

_STORE = config.MEMORY_DIR / "structured_memory.json"
_LOCK = threading.RLock()

MEMORY_TYPES = ("fact", "preference", "task", "contact_note")


def _load() -> list[dict]:
    if not _STORE.exists():
        return []
    try:
        return json.loads(_STORE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(entries: list[dict]) -> None:
    config.MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    _STORE.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")


def remember(text: str, mem_type: str = "fact", key: str = "") -> str:
    """Store a typed memory. A matching (type, key) is overwritten, not duplicated."""
    text = (text or "").strip()
    if not text:
        return "Nothing to remember, Sir."
    if mem_type not in MEMORY_TYPES:
        mem_type = "fact"
    with _LOCK:
        entries = _load()
        if key:
            for e in entries:
                if e.get("type") == mem_type and e.get("key") == key:
                    e["text"] = text
                    e["created_at"] = time.time()
                    _save(entries)
                    try:
                        from . import semantic_memory
                        semantic_memory.remember_text_background(
                            text,
                            kind=f"memory:{mem_type}",
                            metadata={"key": key or ""},
                        )
                    except Exception:
                        pass
                    return f"Updated {mem_type} '{key}', Sir."
        entries.append({
            "id": uuid.uuid4().hex[:12],
            "type": mem_type,
            "text": text,
            "key": key,
            "created_at": time.time(),
        })
        _save(entries)
    try:
        from . import semantic_memory
        semantic_memory.remember_text_background(
            text,
            kind=f"memory:{mem_type}",
            metadata={"key": key or ""},
        )
    except Exception:
        pass
    return f"Noted that {mem_type}, Sir."


def semantic_recall(query: str, limit: int = 3) -> str:
    """Recall memories by meaning using the Chroma-backed semantic store."""
    query = (query or "").strip()
    if not query:
        return "What should I search my memory for, Sir?"
    try:
        from . import semantic_memory
        docs = semantic_memory.recall(query, k=limit)
    except Exception:
        docs = []
    if not docs:
        # Fall back to exact JSON search when embeddings are unavailable.
        exact = recall(query=query)
        docs = [e.get("text", "") for e in exact]
    if not docs:
        return "I did not find anything matching that memory, Sir."
    return "I remember: " + "; ".join(docs[:limit])


def recall(mem_type: str = "", query: str = "") -> list[dict]:
    """Return entries filtered by type and/or a case-insensitive substring."""
    q = (query or "").strip().lower()
    with _LOCK:
        entries = _load()
    out = []
    for e in entries:
        if mem_type and e.get("type") != mem_type:
            continue
        if q and q not in e.get("text", "").lower() and q not in e.get("key", "").lower():
            continue
        out.append(e)
    return out


def summary(mem_type: str = "") -> str:
    """Human-readable list for the 'what do you remember' command."""
    entries = recall(mem_type=mem_type)
    if not entries:
        return "I have nothing stored, Sir." if not mem_type else f"No {mem_type} stored, Sir."
    by_type: dict[str, list[str]] = {}
    for e in entries:
        by_type.setdefault(e["type"], []).append(e["text"])
    parts = []
    for t in MEMORY_TYPES:
        if t in by_type:
            parts.append(f"{t}: " + "; ".join(by_type[t]))
    return ". ".join(parts)


def forget(query: str = "", mem_type: str = "", entry_id: str = "") -> str:
    """Delete by exact id, or by (type, substring). Returns count removed."""
    q = (query or "").strip().lower()
    with _LOCK:
        entries = _load()
        before = len(entries)
        if entry_id:
            entries = [e for e in entries if e.get("id") != entry_id]
        else:
            def _keep(e: dict) -> bool:
                if mem_type and e.get("type") != mem_type:
                    return True
                if q and q not in e.get("text", "").lower() and q not in e.get("key", "").lower():
                    return True
                # Drop only when a real filter matched something.
                return not (q or mem_type)
            entries = [e for e in entries if _keep(e)]
        removed = before - len(entries)
        if removed:
            _save(entries)
    if removed == 0:
        return "Nothing matched, Sir."
    return f"Forgot {removed} item{'s' if removed != 1 else ''}, Sir."


def export_all() -> list[dict]:
    """Return the full store for an 'export my data' command."""
    with _LOCK:
        return _load()


# Voice-facing skills (registered only if you wire them into skills/__init__).
SKILLS = [
    ({"name": "remember_this",
      "description": "Store a durable personal memory. type can be fact, preference, task, or contact_note.",
      "parameters": {"type": "object",
                     "properties": {"text": {"type": "string"},
                                    "mem_type": {"type": "string"},
                                    "key": {"type": "string"}},
                     "required": ["text"]}}, remember),
    ({"name": "what_do_you_remember",
      "description": "List stored personal memories, optionally filtered by type.",
      "parameters": {"type": "object",
                     "properties": {"mem_type": {"type": "string"}}}}, summary),
    ({"name": "semantic_memory_recall",
      "description": "Search stored memories and past conversation by meaning.",
      "parameters": {"type": "object",
                     "properties": {"query": {"type": "string"},
                                    "limit": {"type": "integer"}},
                     "required": ["query"]}}, semantic_recall),
    ({"name": "forget_that",
      "description": "Delete a stored personal memory matching a query or type.",
      "parameters": {"type": "object",
                     "properties": {"query": {"type": "string"},
                                    "mem_type": {"type": "string"}}}}, forget),
]
