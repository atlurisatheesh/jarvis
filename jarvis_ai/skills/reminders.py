"""Reminder/alarm skills. Parses relative ('in 10 minutes') and clock times."""
import re
from datetime import datetime, timedelta

from .. import scheduler


def _parse_when(when: str) -> datetime:
    when = when.strip().lower()
    now = datetime.now()

    m = re.search(r"in\s+(\d+)\s*(second|minute|hour|day)s?", when)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        delta = {"second": "seconds", "minute": "minutes",
                 "hour": "hours", "day": "days"}[unit]
        return now + timedelta(**{delta: n})

    m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", when)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2) or 0)
        ampm = m.group(3)
        if ampm == "pm" and hour < 12:
            hour += 12
        if ampm == "am" and hour == 12:
            hour = 0
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return target

    return now + timedelta(minutes=5)


def set_reminder(when: str, text: str) -> str:
    due = _parse_when(when)
    scheduler.add_reminder(due.isoformat(), text)
    return f"Reminder set for {due.strftime('%I:%M %p on %d %b')}: {text}"


def list_reminders() -> str:
    items = scheduler.list_reminders()
    if not items:
        return "No pending reminders."
    return "Pending: " + "; ".join(
        f"{r['text']} at {datetime.fromisoformat(r['when']).strftime('%I:%M %p')}"
        for r in items
    )


SKILLS = [
    ({"name": "set_reminder",
      "description": "Set a reminder/alarm. 'when' can be relative ('in 10 minutes') or a clock time ('6 am', '18:30').",
      "parameters": {"type": "object",
                     "properties": {"when": {"type": "string"}, "text": {"type": "string"}},
                     "required": ["when", "text"]}}, set_reminder),
    ({"name": "list_reminders", "description": "List pending reminders.",
      "parameters": {"type": "object", "properties": {}}}, list_reminders),
]
