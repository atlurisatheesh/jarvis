"""Enhanced Google Drive operations.

    - Search files by name (read)
    - Read document text content via Google Docs export (read)
    - List recent files (read)
"""
from __future__ import annotations

import webbrowser
from urllib.parse import urlencode

from .google_services import get_service, _check_rate


def search(query: str) -> str:
    """Search Drive files by name."""
    if not _check_rate("drive"):
        return "Drive rate limit reached."
    service = get_service("drive", "v3")
    safe = query.replace("'", "\\'")
    files = (
        service.files()
        .list(
            q=f"name contains '{safe}' and trashed = false",
            pageSize=5,
            fields="files(id,name,mimeType,modifiedTime)",
        )
        .execute()
        .get("files", [])
    )
    if not files:
        return f"No Drive files matching {query}."
    return "Drive: " + "; ".join(f["name"] for f in files)


def read_document(file_id: str) -> str:
    """Read the text content of a Google Doc by exporting as plain text."""
    if not _check_rate("drive"):
        return "Drive rate limit reached."
    service = get_service("drive", "v3")
    try:
        content = (
            service.files()
            .export(fileId=file_id, mimeType="text/plain")
            .execute()
        )
        if isinstance(content, bytes):
            content = content.decode("utf-8", errors="replace")
        return content[:3000] if content else "(empty document)"
    except Exception as e:
        return f"Could not read document: {e}"


def list_recent(count: int = 10) -> str:
    """List recently modified files."""
    if not _check_rate("drive"):
        return "Drive rate limit reached."
    service = get_service("drive", "v3")
    files = (
        service.files()
        .list(
            q="trashed = false",
            pageSize=max(1, min(int(count), 20)),
            orderBy="modifiedTime desc",
            fields="files(id,name,mimeType,modifiedTime)",
        )
        .execute()
        .get("files", [])
    )
    if not files:
        return "No Drive files found."
    return "Recent files: " + "; ".join(f["name"] for f in files)


def open_in_browser(file_id: str) -> str:
    """Open a Drive file in the default browser."""
    url = f"https://drive.google.com/file/d/{file_id}/view"
    webbrowser.open(url)
    return f"Opening file in browser."
