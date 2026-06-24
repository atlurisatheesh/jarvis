"""Enhanced Google Calendar operations.

    - List upcoming events (read)
    - Create events with preview/confirmation (reversible)
    - Search events by date range (read)
    - Delete events with confirmation (destructive)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .google_services import get_service, _check_rate


def _fmt_event(ev: dict) -> str:
    """Format a single event dict as a readable string."""
    summary = ev.get("summary", "Untitled")
    start = ev.get("start", {})
    when = start.get("dateTime", start.get("date", ""))
    if "T" in when:
        try:
            dt = datetime.fromisoformat(when.replace("Z", "+00:00"))
            when = dt.strftime("%a %d %b %I:%M %p")
        except Exception:
            pass
    return f"{summary} at {when}"


def list_upcoming(days: int = 7) -> str:
    """List upcoming events from the primary calendar."""
    if not _check_rate("calendar"):
        return "Calendar rate limit reached. Try again shortly, Sir."
    service = get_service("calendar", "v3")
    now = datetime.now(timezone.utc)
    until = now + timedelta(days=max(1, min(int(days), 30)))
    events = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=now.isoformat(),
            timeMax=until.isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=10,
        )
        .execute()
        .get("items", [])
    )
    if not events:
        return "No upcoming calendar events, Sir."
    return "Upcoming: " + "; ".join(_fmt_event(e) for e in events)


def search_by_date(start_date: str, end_date: str = "") -> str:
    """Search events between two dates (ISO format: YYYY-MM-DD)."""
    # Validate inputs BEFORE touching the rate-limit slot or OAuth. A malformed
    # date should never consume a quota call or trigger a token refresh.
    try:
        start_dt = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
    except ValueError:
        return f"Invalid start date '{start_date}'. Use YYYY-MM-DD."
    if end_date:
        try:
            end_dt = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc) + timedelta(days=1)
        except ValueError:
            return f"Invalid end date '{end_date}'. Use YYYY-MM-DD."
    else:
        end_dt = start_dt + timedelta(days=1)
    if not _check_rate("calendar"):
        return "Calendar rate limit reached."
    service = get_service("calendar", "v3")

    events = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=start_dt.isoformat(),
            timeMax=end_dt.isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=20,
        )
        .execute()
        .get("items", [])
    )
    if not events:
        return f"No events between {start_date} and {end_date or start_date}."
    return f"Events: " + "; ".join(_fmt_event(e) for e in events)


def create_preview(summary: str, start: str, duration_min: int = 60) -> str:
    """Generate a preview of an event to be created (does NOT create yet)."""
    try:
        start_dt = datetime.fromisoformat(start)
    except Exception:
        return "Give a start time like 2026-06-21T15:00, Sir."
    end_dt = start_dt + timedelta(minutes=max(15, min(int(duration_min or 60), 1440)))
    return (
        f"Ready to add '{summary}' on {start_dt:%a %d %b %I:%M %p} "
        f"to {end_dt:%I:%M %p}. Say confirm to add it."
    )


def create(summary: str, start: str, duration_min: int = 60) -> str:
    """Actually create the event (called after confirmation)."""
    # Validate the start time before consuming a rate-limit slot or loading OAuth.
    try:
        start_dt = datetime.fromisoformat(start)
    except Exception:
        return "Give a start time like 2026-06-21T15:00, Sir."
    end_dt = start_dt + timedelta(minutes=max(15, min(int(duration_min or 60), 1440)))
    if not _check_rate("calendar"):
        return "Calendar rate limit reached."
    service = get_service("calendar", "v3")
    body = {
        "summary": summary or "Event",
        "start": {"dateTime": start_dt.isoformat()},
        "end": {"dateTime": end_dt.isoformat()},
    }
    try:
        ev = service.events().insert(calendarId="primary", body=body).execute()
        return f"Added '{body['summary']}' on {start_dt:%a %d %b %I:%M %p}, Sir."
    except Exception as e:
        return f"Calendar error: {e}"


def delete(event_id: str) -> str:
    """Delete an event by ID (destructive — confirmation handled by policy)."""
    if not _check_rate("calendar"):
        return "Calendar rate limit reached."
    service = get_service("calendar", "v3")
    try:
        service.events().delete(calendarId="primary", eventId=event_id).execute()
        return f"Deleted event {event_id}, Sir."
    except Exception as e:
        return f"Delete error: {e}"
