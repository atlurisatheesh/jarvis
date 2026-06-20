"""Personal context: search across the user's own files like Siri AI 2026.

- search_file_contents: grep INSIDE text/doc files (search_files only matches names)
- recent_files: what changed lately
- find_anything: name + content combined, ranked
"""
import os
import time
from pathlib import Path

_TEXT_EXT = {".txt", ".md", ".py", ".js", ".ts", ".json", ".csv", ".log",
             ".html", ".css", ".yaml", ".yml", ".ini", ".cfg", ".xml"}
_SKIP_DIRS = {"node_modules", ".git", "__pycache__", ".venv", "venv",
              "AppData", ".cache", "site-packages", "dist", "build"}


def _walk(base: Path):
    """Yield files under base, skipping noisy dirs."""
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
        for name in files:
            yield Path(root) / name


def search_file_contents(query: str, folder: str = "~", limit: int = 8) -> str:
    """Find files whose CONTENTS contain the query (case-insensitive)."""
    base = Path(os.path.expanduser(folder))
    if not base.exists():
        return f"Folder not found: {folder}"
    q = query.lower()
    hits = []
    scanned = 0
    for p in _walk(base):
        if p.suffix.lower() not in _TEXT_EXT:
            continue
        scanned += 1
        if scanned > 4000:
            break
        try:
            if p.stat().st_size > 2_000_000:
                continue
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        low = text.lower()
        idx = low.find(q)
        if idx != -1:
            start = max(0, idx - 40)
            snippet = text[start:idx + 60].replace("\n", " ").strip()
            hits.append(f"{p.name}: ...{snippet}...")
            if len(hits) >= limit:
                break
    if not hits:
        return f"No files containing '{query}' found in {folder}."
    return "Found:\n" + "\n".join(hits)


def recent_files(hours: int = 24, folder: str = "~", limit: int = 10) -> str:
    """List files modified in the last N hours, newest first."""
    base = Path(os.path.expanduser(folder))
    if not base.exists():
        return f"Folder not found: {folder}"
    cutoff = time.time() - hours * 3600
    found = []
    scanned = 0
    for p in _walk(base):
        scanned += 1
        if scanned > 20000:
            break
        try:
            mtime = p.stat().st_mtime
        except Exception:
            continue
        if mtime >= cutoff:
            found.append((mtime, p))
    if not found:
        return f"No files changed in the last {hours} hours."
    found.sort(reverse=True)
    out = []
    for mtime, p in found[:limit]:
        when = time.strftime("%H:%M", time.localtime(mtime))
        out.append(f"{p.name} ({when})")
    return "Recently changed:\n" + "\n".join(out)


def find_anything(query: str, folder: str = "~", limit: int = 8) -> str:
    """Find by filename OR contents — combined personal-context search."""
    base = Path(os.path.expanduser(folder))
    if not base.exists():
        return f"Folder not found: {folder}"
    q = query.lower()
    name_hits, content_hits = [], []
    scanned = 0
    for p in _walk(base):
        scanned += 1
        if scanned > 8000:
            break
        if q in p.name.lower():
            name_hits.append(p.name)
            if len(name_hits) >= limit:
                continue
        elif p.suffix.lower() in _TEXT_EXT:
            try:
                if p.stat().st_size > 1_000_000:
                    continue
                if q in p.read_text(encoding="utf-8", errors="ignore").lower():
                    content_hits.append(p.name)
            except Exception:
                pass
    parts = []
    if name_hits:
        parts.append("By name: " + "; ".join(name_hits[:limit]))
    if content_hits:
        parts.append("By content: " + "; ".join(content_hits[:limit]))
    return "\n".join(parts) if parts else f"Nothing matching '{query}' found."


SKILLS = [
    ({"name": "search_file_contents",
      "description": "Search INSIDE files for text (grep). Use to find a file by what it "
                     "contains, not its name.",
      "parameters": {"type": "object", "properties": {
          "query": {"type": "string"},
          "folder": {"type": "string", "description": "Where to search (default home)"},
          "limit": {"type": "integer"},
      }, "required": ["query"]}}, search_file_contents),

    ({"name": "recent_files",
      "description": "List files the user changed recently (last N hours).",
      "parameters": {"type": "object", "properties": {
          "hours": {"type": "integer", "description": "Look back this many hours (default 24)"},
          "folder": {"type": "string"},
          "limit": {"type": "integer"},
      }}}, recent_files),

    ({"name": "find_anything",
      "description": "Find a file by name OR contents — broad personal-context search.",
      "parameters": {"type": "object", "properties": {
          "query": {"type": "string"},
          "folder": {"type": "string"},
          "limit": {"type": "integer"},
      }, "required": ["query"]}}, find_anything),
]
