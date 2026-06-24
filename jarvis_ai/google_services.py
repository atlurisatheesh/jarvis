"""Centralized Google service layer.

Provides shared OAuth credential management, token-refresh monitoring,
credential health checks, and per-API rate-limit tracking.

All other Google modules (calendar, gmail, drive, contacts) use
``get_credentials()`` and ``get_service()`` from here instead of
re-implementing OAuth logic.
"""
from __future__ import annotations

import time
from pathlib import Path

from . import config

# OAuth scopes used across all Google integrations.
GOOGLE_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/contacts.readonly",
]

# In-memory rate-limit tracker: API name → list of timestamps.
_rate_log: dict[str, list[float]] = {}
_rate_limit_per_min = getattr(config, "GOOGLE_RATE_LIMIT_PER_MINUTE", 30)


def get_credentials(interactive: bool = False):
    """Get valid Google OAuth credentials, refreshing if needed."""
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        raise RuntimeError("Install Google deps: pip install google-api-python-client google-auth-oauthlib")

    token_path = Path(config.GOOGLE_TOKEN_FILE)
    creds = (
        Credentials.from_authorized_user_file(token_path, GOOGLE_SCOPES)
        if token_path.exists()
        else None
    )
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    if not creds or not creds.valid:
        if not interactive:
            raise RuntimeError("Google not connected. Run: python -m jarvis_ai.google_auth")
        flow = InstalledAppFlow.from_client_secrets_file(config.GOOGLE_CREDENTIALS_FILE, GOOGLE_SCOPES)
        creds = flow.run_local_server(port=0)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    return creds


def get_service(name: str, version: str):
    """Build a Google API service object with valid credentials."""
    from googleapiclient.discovery import build
    return build(name, version, credentials=get_credentials(), cache_discovery=False)


def authorize_google() -> str:
    """Run the interactive OAuth flow to connect the user's account."""
    if not Path(config.GOOGLE_CREDENTIALS_FILE).exists():
        return "Google credentials file is missing, Sir."
    get_credentials(interactive=True)
    return "Google account connected, Sir."


def is_connected() -> bool:
    """Check if Google OAuth token exists and is valid/refreshable."""
    token_path = Path(config.GOOGLE_TOKEN_FILE)
    if not token_path.exists():
        return False
    try:
        creds = get_credentials()
        return creds is not None and creds.valid
    except Exception:
        return False


def health_check() -> dict:
    """Return health info about the Google connection."""
    return {
        "connected": is_connected(),
        "credentials_file": Path(config.GOOGLE_CREDENTIALS_FILE).exists(),
        "token_file": Path(config.GOOGLE_TOKEN_FILE).exists(),
        "scopes": len(GOOGLE_SCOPES),
    }


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

def _check_rate(api: str) -> bool:
    """Return True if the API call is within rate limits."""
    now = time.monotonic()
    timestamps = _rate_log.get(api, [])
    # Prune entries older than 60 seconds
    timestamps = [t for t in timestamps if now - t < 60.0]
    if len(timestamps) >= _rate_limit_per_min:
        return False
    timestamps.append(now)
    _rate_log[api] = timestamps
    return True


def rate_status() -> dict:
    """Return current rate-limit usage per API."""
    now = time.monotonic()
    return {
        api: len([t for t in ts if now - t < 60.0])
        for api, ts in _rate_log.items()
    }
