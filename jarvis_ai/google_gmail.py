"""Enhanced Gmail operations.

    - Search emails (read)
    - Read full email body (read)
    - Compose with preview → confirm → send flow (external)
    - List unread/recent (read)
"""
from __future__ import annotations

import base64
from email.mime.text import MIMEText

from .google_services import get_service, _check_rate


def _get_message(service, msg_id: str, fmt: str = "metadata") -> dict:
    """Fetch a single message."""
    return (
        service.users()
        .messages()
        .get(userId="me", id=msg_id, format=fmt)
        .execute()
    )


def _extract_headers(msg: dict) -> dict:
    """Extract From/Subject/Date headers from a message."""
    headers = {}
    for h in msg.get("payload", {}).get("headers", []):
        headers[h["name"].lower()] = h["value"]
    return headers


def _extract_body(msg: dict) -> str:
    """Extract the plain-text body from a full-format message."""
    payload = msg.get("payload", {})
    # Simple case: body in payload.parts
    if "body" in payload and payload["body"].get("data"):
        data = payload["body"]["data"]
        return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")[:2000]
    # Multipart: find text/plain part
    for part in payload.get("parts", []):
        mime = part.get("mimeType", "")
        if mime == "text/plain" and part.get("body", {}).get("data"):
            data = part["body"]["data"]
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")[:2000]
    return "(no plain text body)"


def search(query: str = "", limit: int = 5) -> str:
    """Search Gmail and return sender/subject summaries."""
    if not _check_rate("gmail"):
        return "Gmail rate limit reached."
    service = get_service("gmail", "v1")
    messages = (
        service.users()
        .messages()
        .list(userId="me", q=query, maxResults=max(1, min(int(limit), 10)))
        .execute()
        .get("messages", [])
    )
    if not messages:
        return "No matching Gmail messages."
    rows = []
    for item in messages:
        msg = _get_message(service, item["id"])
        headers = _extract_headers(msg)
        rows.append(f"{headers.get('from', 'Unknown')}: {headers.get('subject', '(no subject)')}")
    return "Gmail: " + "; ".join(rows)


def read_message(msg_id: str) -> str:
    """Read the full body of a specific email."""
    if not _check_rate("gmail"):
        return "Gmail rate limit reached."
    service = get_service("gmail", "v1")
    msg = _get_message(service, msg_id, fmt="full")
    headers = _extract_headers(msg)
    body = _extract_body(msg)
    return f"From: {headers.get('from', '?')}\nSubject: {headers.get('subject', '?')}\n\n{body}"


def compose_preview(to: str, subject: str, body: str) -> str:
    """Generate a preview of an email to be sent (does NOT send)."""
    if not to.strip():
        return "Who should I send it to, Sir?"
    return (
        f"Ready to send to {to} — subject '{subject}': {body[:120]}. "
        f"Say confirm to send."
    )


def send(to: str, subject: str, body: str) -> str:
    """Actually send the email (called after confirmation)."""
    if not _check_rate("gmail"):
        return "Gmail rate limit reached."
    msg = MIMEText(body)
    msg["to"] = to
    msg["subject"] = subject or "(no subject)"
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    try:
        service = get_service("gmail", "v1")
        service.users().messages().send(userId="me", body={"raw": raw}).execute()
        return f"Sent to {to}, Sir."
    except Exception as e:
        return f"Send failed: {e}"


def unread_count() -> str:
    """Count unread emails and show recent senders."""
    if not _check_rate("gmail"):
        return "Gmail rate limit reached."
    service = get_service("gmail", "v1")
    messages = (
        service.users()
        .messages()
        .list(userId="me", q="is:unread", maxResults=5)
        .execute()
        .get("messages", [])
    )
    if not messages:
        return "No unread emails, Sir."
    senders = []
    for item in messages:
        msg = _get_message(service, item["id"])
        headers = _extract_headers(msg)
        sender = headers.get("from", "Unknown").split("<")[0].strip()
        senders.append(sender)
    return f"{len(messages)} unread: " + ", ".join(senders)
