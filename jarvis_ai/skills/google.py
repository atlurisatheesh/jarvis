"""Google Maps and OAuth-backed Google personal-data skills.

Delegates Calendar/Gmail/Drive/Contacts to the dedicated Phase 5 modules
(``google_calendar``, ``google_gmail``, ``google_drive``, ``google_contacts``)
which provide enhanced functionality (previews, confirmations, reads).
"""
from urllib.parse import urlencode
import webbrowser

from .. import google_services
from .. import google_calendar
from .. import google_gmail
from .. import google_drive
from .. import google_contacts


def authorize_google() -> str:
    return google_services.authorize_google()


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


# Calendar (Phase 5 — delegated to google_calendar module)
def google_calendar_upcoming(days: int = 7) -> str:
    return google_calendar.list_upcoming(days)


def google_calendar_search(start_date: str, end_date: str = "") -> str:
    return google_calendar.search_by_date(start_date, end_date)


def google_calendar_create(summary: str, start: str, duration_min: int = 60) -> str:
    """Create a Calendar event. First call previews; the confirmation gate
    in ``assistant_core`` handles the yes/no flow."""
    return google_calendar.create(summary, start, duration_min)


def google_calendar_delete(event_id: str) -> str:
    return google_calendar.delete(event_id)


# Gmail (Phase 5 — delegated to google_gmail module)
def google_gmail_search(query: str = "", limit: int = 5) -> str:
    return google_gmail.search(query, limit)


def google_gmail_read(msg_id: str) -> str:
    """Read the full body of a Gmail message."""
    return google_gmail.read_message(msg_id)


def google_gmail_send(to: str, subject: str, body: str, confirm: bool = False) -> str:
    """Send an email. First call WITHOUT confirm previews; read it back to the
    user, then call again with confirm=true after they approve."""
    if not to.strip():
        return "Who should I send it to, Sir?"
    if not confirm:
        return google_gmail.compose_preview(to, subject, body)
    return google_gmail.send(to, subject, body)


# Drive (Phase 5 — delegated to google_drive module)
def google_drive_search(query: str) -> str:
    return google_drive.search(query)


def google_drive_read(file_id: str) -> str:
    """Read the text content of a Google Doc."""
    return google_drive.read_document(file_id)


def google_drive_recent(count: int = 10) -> str:
    return google_drive.list_recent(count)


# Contacts (Phase 5 — delegated to google_contacts module)
def google_contacts_search(query: str) -> str:
    return google_contacts.search(query)


def google_contacts_get(query: str) -> str:
    """Get contact details (name, email, phone)."""
    details = google_contacts.get_details(query)
    if not details:
        return f"No contact named {query}."
    name = details.get("name", "Unknown")
    emails = details.get("emails", [])
    phones = details.get("phones", [])
    parts = [name]
    if emails:
        parts.append(f"email: {emails[0]}")
    if phones:
        parts.append(f"phone: {phones[0]}")
    return ", ".join(parts)


def google_contacts_resolve_phone(query: str) -> str:
    """Resolve a contact name to a phone number."""
    return google_contacts.resolve_phone(query)


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
    ({"name": "google_calendar_search", "description": "Search calendar events between two dates (YYYY-MM-DD).", "parameters": {"type": "object", "properties": {"start_date": {"type": "string"}, "end_date": {"type": "string"}}, "required": ["start_date"]}}, google_calendar_search),
    ({"name": "google_gmail_search", "description": "Search the user's Gmail and return sender and subject summaries.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}}}}, google_gmail_search),
    ({"name": "google_gmail_read", "description": "Read the full body of a Gmail message by ID.", "parameters": {"type": "object", "properties": {"msg_id": {"type": "string"}}, "required": ["msg_id"]}}, google_gmail_read),
    ({"name": "google_drive_search", "description": "Search the user's Google Drive files by name.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}, google_drive_search),
    ({"name": "google_drive_read", "description": "Read the text content of a Google Doc by file ID.", "parameters": {"type": "object", "properties": {"file_id": {"type": "string"}}, "required": ["file_id"]}}, google_drive_read),
    ({"name": "google_drive_recent", "description": "List recently modified Google Drive files.", "parameters": {"type": "object", "properties": {"count": {"type": "integer"}}}}, google_drive_recent),
    ({"name": "google_contacts_search", "description": "Search the user's Google Contacts by name.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}, google_contacts_search),
    ({"name": "google_contacts_get", "description": "Get contact details (name, email, phone) for the best match.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}, google_contacts_get),
    ({"name": "google_calendar_create",
      "description": "Create a Google Calendar event. start is ISO local time like 2026-06-21T15:00.",
      "parameters": {"type": "object", "properties": {
          "summary": {"type": "string"}, "start": {"type": "string"},
          "duration_min": {"type": "integer"}
      }, "required": ["summary", "start"]}}, google_calendar_create),
    ({"name": "google_gmail_send",
      "description": "Send an email. First call WITHOUT confirm to preview; read it back to "
                     "the user, then call again with confirm=true after they approve.",
      "parameters": {"type": "object", "properties": {
          "to": {"type": "string"}, "subject": {"type": "string"},
          "body": {"type": "string"}, "confirm": {"type": "boolean"}
      }, "required": ["to", "subject", "body"]}}, google_gmail_send),
]
