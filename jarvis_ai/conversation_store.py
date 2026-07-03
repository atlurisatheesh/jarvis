"""Persistent conversation log — survives restarts.

The provider brains (Groq/OpenAI/Cloudflare/local) each keep an in-memory
``self.messages`` list for tool-calling context, which is lost on restart. This
module provides a lightweight rolling log of user turns + assistant replies so
the conversation thread can be rehydrated after a crash or restart.

Only the high-level turn pairs (user text -> assistant reply text) are stored,
not the internal tool-call plumbing. On startup each provider brain prepends
the rehydrated turns to its fresh system prompt, restoring conversational
context without replaying tool internals.
"""
from __future__ import annotations

import json
import threading
import time

from . import config

_STORE = config.MEMORY_DIR / "conversation.json"
_LOCK = threading.Lock()


def _load() -> list[dict]:
    if not _STORE.exists():
        return []
    try:
        return json.loads(_STORE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(turns: list[dict]) -> None:
    config.MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    _STORE.write_text(json.dumps(turns, ensure_ascii=False, indent=2), encoding="utf-8")


def save_turn(user: str, assistant: str) -> None:
    """Append a (user, assistant) turn pair to the rolling log.

    Empty/whitespace-only text is skipped. The log is capped to the last
    CONVERSATION_PERSIST_TURNS entries so it stays small.
    """
    if not getattr(config, "CONVERSATION_PERSIST_ENABLED", True):
        return
    user = (user or "").strip()
    assistant = (assistant or "").strip()
    if not user or not assistant:
        return
    with _LOCK:
        turns = _load()
        turns.append({
            "user": user,
            "assistant": assistant,
            "ts": time.time(),
        })
        cap = int(getattr(config, "CONVERSATION_PERSIST_TURNS", 50))
        if len(turns) > cap:
            turns = turns[-cap:]
        _save(turns)
    try:
        from . import semantic_memory
        semantic_memory.remember_text_background(
            f"User: {user}\nAssistant: {assistant}",
            kind="conversation",
        )
    except Exception:
        pass


def load_recent(n: int = 20) -> list[dict]:
    """Return the last *n* turn pairs (oldest first), or [] if none/disabled."""
    if not getattr(config, "CONVERSATION_PERSIST_ENABLED", True):
        return []
    with _LOCK:
        turns = _load()
    if not turns:
        return []
    return turns[-n:]


def clear() -> None:
    """Wipe the conversation log ('Leha, forget our conversation')."""
    with _LOCK:
        _save([])


def summary(limit: int = 5) -> str:
    """Short human-readable summary of recent conversation turns."""
    turns = load_recent(limit)
    if not turns:
        return "No recent conversation stored, Sir."
    parts = []
    for t in turns:
        user = str(t.get("user", ""))[:80]
        assistant = str(t.get("assistant", ""))[:80]
        parts.append(f"You: {user} / Leha: {assistant}")
    return "Recent conversation: " + " | ".join(parts)


def as_messages(n: int = 20) -> list[dict]:
    """Return rehydrated turns as OpenAI-style {role, content} messages.

    Intended to be spliced into a provider brain's ``self.messages`` right
    after the system prompt so the model remembers prior context.
    """
    out: list[dict] = []
    for t in load_recent(n):
        out.append({"role": "user", "content": t["user"]})
        out.append({"role": "assistant", "content": t["assistant"]})
    return out
