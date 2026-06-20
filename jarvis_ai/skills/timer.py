"""Timer / stopwatch skill."""
from datetime import datetime, timedelta

from ..scheduler import add_reminder, list_reminders


def set_timer(minutes: int, label: str = "timer") -> str:
    due = (datetime.now() + timedelta(minutes=minutes)).isoformat()
    add_reminder(due, f"{label} is up")
    return f"Timer set for {minutes} minute{'s' if minutes != 1 else ''}."


def list_timers() -> str:
    items = list_reminders()
    return f"You have {len(items)} active reminder(s)." if items else "No active timers."


SKILLS = [
    (
        {
            "name": "set_timer",
            "description": "Set a timer for N minutes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "minutes": {"type": "integer"},
                    "label": {"type": "string"},
                },
                "required": ["minutes"],
            },
        },
        set_timer,
    ),
    (
        {
            "name": "list_timers",
            "description": "List active timers and reminders.",
            "parameters": {"type": "object", "properties": {}},
        },
        list_timers,
    ),
]
