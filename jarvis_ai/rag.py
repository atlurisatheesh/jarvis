"""RAG over your own documents: ChromaDB + Ollama embeddings (nomic-embed-text).

Ingest a folder of .txt/.md/.pdf, then query — JARVIS answers from YOUR docs.
"""
from pathlib import Path

import chromadb
import ollama

from . import config

_client = None
_collection = None


def _coll():
    global _client, _collection
    if _collection is None:
        config.MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(path=str(config.MEMORY_DIR / "chroma"))
        _collection = _client.get_or_create_collection("docs")
    return _collection


def _embed(text: str):
    r = ollama.Client(host=config.OLLAMA_HOST).embeddings(
        model=config.EMBED_MODEL, prompt=text
    )
    return r["embedding"]


def _read_file(p: Path) -> str:
    if p.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader
            return "\n".join((pg.extract_text() or "") for pg in PdfReader(str(p)).pages)
        except Exception:
            return ""
    try:
        return p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _chunks(text: str, size=800, overlap=100):
    words = text.split()
    i = 0
    while i < len(words):
        yield " ".join(words[i:i + size])
        i += size - overlap


def ingest(folder: str) -> str:
    base = Path(folder).expanduser()
    if not base.exists():
        return f"Folder not found: {folder}"
    coll = _coll()
    n = 0
    for p in base.rglob("*"):
        if p.suffix.lower() not in {".txt", ".md", ".pdf"}:
            continue
        text = _read_file(p)
        if not text.strip():
            continue
        for j, chunk in enumerate(_chunks(text)):
            try:
                coll.upsert(ids=[f"{p.name}_{j}"],
                            embeddings=[_embed(chunk)],
                            documents=[chunk],
                            metadatas=[{"source": p.name}])
                n += 1
            except Exception:
                pass
    return f"Ingested {n} chunks from {base}."


def query(question: str, k=4) -> str:
    coll = _coll()
    if coll.count() == 0:
        return ""
    res = coll.query(query_embeddings=[_embed(question)], n_results=k)
    docs = res.get("documents", [[]])[0]
    return "\n---\n".join(docs)
