"""Background scheduler for reminders and daily briefings.

Runs in its own thread with its own TTS engine so it can speak independently
of the main voice loop. Reminders persist to JSON so they survive restarts.
"""
import json
import threading
import time
from datetime import datetime, timedelta

from . import config

_REM_FILE = config.MEMORY_DIR / "reminders.json"
_lock = threading.Lock()


def _load():
    if _REM_FILE.exists():
        try:
            return json.loads(_REM_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def _save(items):
    config.MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    _REM_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def add_reminder(when_iso: str, text: str):
    with _lock:
        items = _load()
        items.append({"when": when_iso, "text": text, "done": False})
        _save(items)


def list_reminders():
    return [r for r in _load() if not r.get("done")]


class Scheduler(threading.Thread):
    def __init__(self, mouth=None, brief_callback=None):
        super().__init__(daemon=True)
        self._mouth = mouth
        self._brief_callback = brief_callback
        self._last_brief_date = None

    def _speak(self, text):
        if self._mouth:
            try:
                self._mouth.say(text)
                return
            except Exception:
                pass
        print(f"[reminder] {text}")

    def run(self):
        while True:
            now = datetime.now()
            with _lock:
                items = _load()
                changed = False
                for r in items:
                    if r.get("done"):
                        continue
                    try:
                        due = datetime.fromisoformat(r["when"])
                    except Exception:
                        continue
                    if now >= due:
                        self._speak(f"Reminder, Sir: {r['text']}")
                        r["done"] = True
                        changed = True
                if changed:
                    _save(items)

            # daily briefing at configured hour
            if (self._brief_callback and now.hour == config.BRIEF_HOUR
                    and self._last_brief_date != now.date()):
                self._last_brief_date = now.date()
                try:
                    self._brief_callback()
                except Exception as e:
                    print(f"[scheduler] brief error: {e}")

            time.sleep(15)
