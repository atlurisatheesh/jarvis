"""Simple persistent long-term memory (JSON facts).

Kept deliberately simple so it always works offline with zero extra deps.
Upgrade path: swap this for ChromaDB vector memory later (Phase 3+).
"""
import json
from . import config

MEM_FILE = config.MEMORY_DIR / "facts.json"


def _load():
    if MEM_FILE.exists():
        try:
            return json.loads(MEM_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def remember(fact: str) -> str:
    config.MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    facts = _load()
    facts.append(fact.strip())
    MEM_FILE.write_text(
        json.dumps(facts, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return "Noted, Sir."


def all_facts():
    return _load()
