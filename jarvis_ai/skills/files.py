"""File and folder skills."""
import os
from pathlib import Path


def open_path(path: str) -> str:
    target = os.path.expandvars(os.path.expanduser(path))
    os.startfile(target)  # Windows
    return f"Opening {path}."


def search_files(query: str, folder: str = "~", limit: int = 10) -> str:
    base = Path(os.path.expanduser(folder))
    hits = []
    try:
        for p in base.rglob(f"*{query}*"):
            hits.append(str(p))
            if len(hits) >= limit:
                break
    except Exception as e:
        return f"Search error: {e}"
    return "Found: " + "; ".join(hits) if hits else "No matching files found."


SKILLS = [
    ({"name": "open_path",
      "description": "Open a file or folder by path (supports ~ and env vars).",
      "parameters": {"type": "object",
                     "properties": {"path": {"type": "string"}}, "required": ["path"]}}, open_path),
    ({"name": "search_files",
      "description": "Search for files whose name contains a query, under a folder (default home).",
      "parameters": {"type": "object",
                     "properties": {"query": {"type": "string"},
                                    "folder": {"type": "string"},
                                    "limit": {"type": "integer"}},
                     "required": ["query"]}}, search_files),
]
