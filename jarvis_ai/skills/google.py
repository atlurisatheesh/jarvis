"""Google Maps and OAuth-backed Google personal-data skills."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
import webbrowser

from .. import config

GOOGLE_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/contacts.readonly",
]


def _credentials(interactive: bool = False):
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        raise RuntimeError("Install Google dependencies with: pip install -r requirements.txt")
    token_path = Path(config.GOOGLE_TOKEN_FILE)
    creds = Credentials.from_authorized_user_file(token_path, GOOGLE_SCOPES) if token_path.exists() else None
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    if not creds or not creds.valid:
        if not interactive:
            raise RuntimeError("Google is not connected. Run: python -m jarvis_ai.google_auth")
        flow = InstalledAppFlow.from_client_secrets_file(config.GOOGLE_CREDENTIALS_FILE, GOOGLE_SCOPES)
        creds = flow.run_local_server(port=0)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    return creds


def authorize_google() -> str:
    if not Path(config.GOOGLE_CREDENTIALS_FILE).exists():
        return "Google credentials file is missing."
    _credentials(interactive=True)
    return "Google account connected."


def _service(name: str, version: str):
    from googleapiclient.discovery import build
    return build(name, version, credentials=_credentials(), cache_discovery=False)


def open_google_maps(destination: str, origin: str = "") -> str:
    """Open Google Maps directions in the default browser."""
    destination = (destination or "").strip()
    if not destination:
        return "Tell me where you want to go."
    params = {"api": "1", "destination": destination, "travelmode": "driving"}
    if origin.strip():
        params["origin"] = origin.strip()
    webbrowser.open("https://www.google.com/maps/dir/?" + urlencode(params))
    return f"Opening Google Maps directions to {destination}."


def search_google_maps(query: str) -> str:
    """Search Google Maps for a place or business."""
    query = (query or "").strip()
    if not query:
        return "Tell me what place to search for."
    webbrowser.open("https://www.google.com/maps/search/?" + urlencode({"api": "1", "query": query}))
    return f"Searching Google Maps for {query}."


def google_calendar_upcoming(days: int = 7) -> str:
    service = _service("calendar", "v3")
    until = datetime.now(timezone.utc) + timedelta(days=max(1, min(int(days), 30)))
    events = service.events().list(calendarId="primary", timeMin=datetime.now(timezone.utc).isoformat(),
        timeMax=until.isoformat(), singleEvents=True, orderBy="startTime", maxResults=5).execute().get("items", [])
    if not events:
        return "No upcoming calendar events."
    return "Upcoming: " + "; ".join(f"{e.get('summary', 'Untitled')} at {e.get('start', {}).get('dateTime', e.get('start', {}).get('date', ''))}" for e in events)


def google_gmail_search(query: str = "", limit: int = 5) -> str:
    """Search Gmail through the approved OAuth account, returning message summaries."""
    service = _service("gmail", "v1")
    messages = service.users().messages().list(userId="me", q=query, maxResults=max(1, min(int(limit), 10))).execute().get("messages", [])
    if not messages:
        return "No matching Gmail messages."
    rows = []
    for item in messages:
        msg = service.users().messages().get(userId="me", id=item["id"], format="metadata", metadataHeaders=["From", "Subject"]).execute()
        headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
        rows.append(f"{headers.get('from', 'Unknown')}: {headers.get('subject', '(no subject)')}")
    return "Gmail: " + "; ".join(rows)


def google_drive_search(query: str) -> str:
    service = _service("drive", "v3")
    safe = query.replace("'", "\\'")
    files = service.files().list(q=f"name contains '{safe}' and trashed = false", pageSize=5,
        fields="files(id,name,mimeType,modifiedTime)").execute().get("files", [])
    return "Drive: " + "; ".join(f["name"] for f in files) if files else f"No Drive files matching {query}."


def google_contacts_search(query: str) -> str:
    service = _service("people", "v1")
    people = service.people().searchContacts(query=query, readMask="names,emailAddresses,phoneNumbers", pageSize=5).execute().get("results", [])
    names = [r.get("person", {}).get("names", [{}])[0].get("displayName", "Unknown") for r in people]
    return "Contacts: " + "; ".join(names) if names else f"No contacts matching {query}."


SKILLS = [
    ({"name": "authorize_google", "description": "Connect the user's Google account using the local OAuth browser flow.", "parameters": {"type": "object", "properties": {}}}, authorize_google),
    ({"name": "open_google_maps",
      "description": "Open driving directions in Google Maps to a destination.",
      "parameters": {"type": "object", "properties": {
          "destination": {"type": "string"}, "origin": {"type": "string"}
      }, "required": ["destination"]}}, open_google_maps),
    ({"name": "search_google_maps",
      "description": "Search Google Maps for a place, shop, restaurant, or address.",
      "parameters": {"type": "object", "properties": {
          "query": {"type": "string"}
      }, "required": ["query"]}}, search_google_maps),
    ({"name": "google_calendar_upcoming", "description": "List upcoming Google Calendar events.", "parameters": {"type": "object", "properties": {"days": {"type": "integer"}}}}, google_calendar_upcoming),
    ({"name": "google_gmail_search", "description": "Search the user's Gmail through Google OAuth and return sender and subject summaries.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}}}}, google_gmail_search),
    ({"name": "google_drive_search", "description": "Search the user's Google Drive files by name.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}, google_drive_search),
    ({"name": "google_contacts_search", "description": "Search the user's Google Contacts by name.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}, google_contacts_search),
]
