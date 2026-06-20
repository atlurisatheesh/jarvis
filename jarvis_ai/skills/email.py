"""Gmail personal context: search + read email like Siri AI 2026.

Uses IMAP (stdlib, no extra deps) + a Gmail App Password.
Gmail search syntax supported via X-GM-RAW (e.g. "from:mom hotel confirmation").

Setup (one time):
  1. Enable 2-Step Verification on the Google account.
  2. https://myaccount.google.com/apppasswords -> create app password.
  3. Save the 16-char password to D:\jarvis\.gmail_creds  (gitignored).
  4. Set GMAIL_ADDRESS in config.py / env.
"""
import imaplib
import email
import socket
from email.header import decode_header

from .. import config

_IMAP_HOST = "imap.gmail.com"


def _decode(raw) -> str:
    if not raw:
        return ""
    parts = []
    for text, enc in decode_header(raw):
        if isinstance(text, bytes):
            try:
                parts.append(text.decode(enc or "utf-8", errors="ignore"))
            except (LookupError, TypeError):
                parts.append(text.decode("utf-8", errors="ignore"))
        else:
            parts.append(text)
    return "".join(parts).strip()


def _connect():
    addr = getattr(config, "GMAIL_ADDRESS", "")
    pw = getattr(config, "GMAIL_APP_PASSWORD", "")
    if not addr or not pw:
        return None, ("Gmail not set up, Sir. Save an app password to .gmail_creds "
                      "and set GMAIL_ADDRESS.")
    try:
        socket.setdefaulttimeout(12)
        M = imaplib.IMAP4_SSL(_IMAP_HOST)
        M.login(addr, pw)
        return M, ""
    except Exception as e:
        return None, f"Gmail login failed: {e}"


def _fetch_headers(M, ids, limit):
    out = []
    for num in reversed(ids[-limit:]):
        typ, data = M.fetch(num, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
        if typ != "OK" or not data or not data[0]:
            continue
        msg = email.message_from_bytes(data[0][1])
        frm = _decode(msg.get("From", ""))
        subj = _decode(msg.get("Subject", "(no subject)"))
        # shorten "Name <addr>" -> Name
        if "<" in frm:
            frm = frm.split("<")[0].strip().strip('"') or frm
        out.append(f"{frm}: {subj}")
    return out


def search_email(query: str, limit: int = 5) -> str:
    """Search Gmail with Gmail's own search syntax (X-GM-RAW)."""
    M, err = _connect()
    if not M:
        return err
    try:
        M.select("INBOX", readonly=True)
        typ, data = M.search(None, "X-GM-RAW", f'"{query}"')
        if typ != "OK" or not data or not data[0]:
            return f"No email matching '{query}'."
        ids = data[0].split()
        if not ids:
            return f"No email matching '{query}'."
        rows = _fetch_headers(M, ids, limit)
        return f"Email matching '{query}':\n" + "\n".join(rows)
    except Exception as e:
        return f"Email search error: {e}"
    finally:
        try:
            M.logout()
        except Exception:
            pass


def recent_email(count: int = 5) -> str:
    """List the latest inbox emails."""
    M, err = _connect()
    if not M:
        return err
    try:
        M.select("INBOX", readonly=True)
        typ, data = M.search(None, "ALL")
        if typ != "OK" or not data or not data[0]:
            return "Inbox is empty."
        ids = data[0].split()
        rows = _fetch_headers(M, ids, count)
        return "Latest email:\n" + "\n".join(rows)
    except Exception as e:
        return f"Email error: {e}"
    finally:
        try:
            M.logout()
        except Exception:
            pass


def unread_email() -> str:
    """Count unread email and show who they're from."""
    M, err = _connect()
    if not M:
        return err
    try:
        M.select("INBOX", readonly=True)
        typ, data = M.search(None, "UNSEEN")
        if typ != "OK" or not data or not data[0]:
            return "No unread email, Sir."
        ids = data[0].split()
        n = len(ids)
        if n == 0:
            return "No unread email, Sir."
        rows = _fetch_headers(M, ids, min(n, 5))
        head = f"{n} unread email" + ("s" if n != 1 else "") + ":\n"
        return head + "\n".join(rows)
    except Exception as e:
        return f"Email error: {e}"
    finally:
        try:
            M.logout()
        except Exception:
            pass


SKILLS = [
    ({"name": "search_email",
      "description": "Search the user's Gmail using Gmail search syntax "
                     "(e.g. 'from:mom hotel', 'subject:invoice'). Returns sender + subject.",
      "parameters": {"type": "object", "properties": {
          "query": {"type": "string"},
          "limit": {"type": "integer"},
      }, "required": ["query"]}}, search_email),

    ({"name": "recent_email",
      "description": "List the most recent emails in the inbox.",
      "parameters": {"type": "object", "properties": {
          "count": {"type": "integer"},
      }}}, recent_email),

    ({"name": "unread_email",
      "description": "Count unread emails and show who they are from.",
      "parameters": {"type": "object", "properties": {}}}, unread_email),
]
