"""Semantic memory over the existing ChromaDB/RAG stack.

This stores conversation turns and structured memories in a separate Chroma
collection named ``memory``. Indexing is best-effort: if ChromaDB or Ollama
embeddings are unavailable, the assistant keeps working with JSON memory.
"""
from __future__ import annotations

import hashlib
import threading
import time

import ollama

from . import config

_client = None
_collection = None
_lock = threading.RLock()


def _enabled() -> bool:
    return bool(getattr(config, "SEMANTIC_MEMORY_ENABLED", True))


def _coll():
    global _client, _collection
    if not _enabled():
        return None
    with _lock:
        if _collection is None:
            import chromadb
            config.MEMORY_DIR.mkdir(parents=True, exist_ok=True)
            _client = chromadb.PersistentClient(path=str(config.MEMORY_DIR / "chroma"))
            _collection = _client.get_or_create_collection("memory")
        return _collection


def _embed(text: str):
    return ollama.Client(host=config.OLLAMA_HOST).embeddings(
        model=config.EMBED_MODEL,
        prompt=text,
    )["embedding"]


def _doc_id(kind: str, text: str) -> str:
    digest = hashlib.sha1(f"{kind}\n{text}".encode("utf-8", errors="ignore")).hexdigest()
    return f"{kind}_{digest[:20]}"


def remember_text(text: str, *, kind: str = "conversation", metadata: dict | None = None) -> bool:
    """Index text for semantic recall. Returns False on any non-fatal failure."""
    text = (text or "").strip()
    if not text or not _enabled():
        return False
    try:
        coll = _coll()
        if coll is None:
            return False
        meta = {"kind": kind, "ts": time.time()}
        if metadata:
            meta.update({str(k): str(v) for k, v in metadata.items()})
        coll.upsert(
            ids=[_doc_id(kind, text)],
            embeddings=[_embed(text)],
            documents=[text],
            metadatas=[meta],
        )
        return True
    except Exception as exc:
        print(f"[semantic-memory] index skipped: {exc}", flush=True)
        return False


def remember_text_background(text: str, *, kind: str = "conversation", metadata: dict | None = None) -> None:
    """Index text in a daemon thread so the voice loop stays responsive."""
    if not text or not _enabled():
        return
    threading.Thread(
        target=remember_text,
        kwargs={"text": text, "kind": kind, "metadata": metadata},
        daemon=True,
    ).start()


def recall(query: str, k: int | None = None) -> list[str]:
    """Return semantically similar memory snippets, best-effort."""
    query = (query or "").strip()
    if not query or not _enabled():
        return []
    try:
        coll = _coll()
        if coll is None or coll.count() == 0:
            return []
        n = int(k or getattr(config, "SEMANTIC_MEMORY_RESULTS", 3))
        res = coll.query(query_embeddings=[_embed(query)], n_results=n)
        return [d for d in res.get("documents", [[]])[0] if d]
    except Exception as exc:
        print(f"[semantic-memory] recall skipped: {exc}", flush=True)
        return []


def context_for(query: str, k: int | None = None) -> str:
    """Small context block suitable for a model prompt."""
    docs = recall(query, k=k)
    if not docs:
        return ""
    return "Relevant memory:\n" + "\n---\n".join(docs)
