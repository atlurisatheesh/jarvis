"""Android control skills via ADB (Phase 5).

Requires: USB debugging enabled on the phone, adb on PATH (or set ADB_PATH),
and the phone connected by USB or 'adb connect <ip>' over WiFi.
"""
import subprocess
import time

from .. import config


def _adb(*args, timeout=20) -> str:
    try:
        r = subprocess.run(
            [config.ADB_PATH, *args], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout
        )
        return (r.stdout or r.stderr).strip()
    except FileNotFoundError:
        return "adb not found. Install Android platform-tools and set ADB_PATH."
    except Exception as e:
        return f"adb error: {e}"


def phone_status() -> str:
    out = _adb("devices")
    return out or "No phone detected."


def phone_open_app(package: str) -> str:
    _adb("shell", "monkey", "-p", package,
         "-c", "android.intent.category.LAUNCHER", "1")
    return f"Opening {package} on the phone."


def phone_send_sms(number: str, message: str) -> str:
    _adb("shell", "am", "start", "-a", "android.intent.action.SENDTO",
         "-d", f"sms:{number}", "--es", "sms_body", message)
    return f"SMS to {number} drafted on the phone (tap send)."


def phone_key(key: str) -> str:
    codes = {"home": "KEYCODE_HOME", "back": "KEYCODE_BACK",
             "recents": "KEYCODE_APP_SWITCH", "power": "KEYCODE_POWER"}
    code = codes.get(key)
    if not code:
        return "key must be home, back, recents or power."
    _adb("shell", "input", "keyevent", code)
    return f"Pressed {key} on the phone."


def phone_type(text: str) -> str:
    _adb("shell", "input", "text", text.replace(" ", "%s"))
    return "Typed on the phone."


def phone_screenshot() -> str:
    remote = "/sdcard/jarvis_shot.png"
    _adb("shell", "screencap", "-p", remote)
    local = f"phone_shot_{int(time.time())}.png"
    _adb("pull", remote, local)
    return f"Phone screenshot saved to {local}."


def phone_notifications() -> str:
    """Read recent notification titles/text from the phone."""
    out = _adb("shell", "dumpsys", "notification", "--noredact")
    lines = [ln.strip() for ln in out.splitlines()
             if "tickerText=" in ln or "android.title=" in ln or "android.text=" in ln]
    cleaned = []
    for ln in lines[:15]:
        val = ln.split("=", 1)[-1].strip()
        if val and val.lower() not in ("null", ""):
            cleaned.append(val)
    return "Notifications: " + "; ".join(cleaned[:8]) if cleaned else "No readable notifications."


def phone_ring() -> str:
    """Make the phone ring to find it: max volume + play a tone."""
    _adb("shell", "media", "volume", "--stream", "3", "--set", "15")
    _adb("shell", "am", "start", "-a", "android.intent.action.VIEW",
         "-d", "https://www.google.com", "-t", "text/html")
    _adb("shell", "input", "keyevent", "KEYCODE_VOLUME_UP")
    return "Ringing the phone (volume maxed)."


def phone_whatsapp(number: str, message: str) -> str:
    """Open a WhatsApp chat to a number with a prefilled message (tap send)."""
    import urllib.parse
    msg = urllib.parse.quote(message)
    num = number.lstrip("+")
    _adb("shell", "am", "start", "-a", "android.intent.action.VIEW",
         "-d", f"https://wa.me/{num}?text={msg}")
    return f"WhatsApp chat to {number} opened with your message (tap send)."


def _parse_sms_rows(out: str, limit: int) -> list:
    """Parse 'adb content query' Row output into (sender, body) pairs.

    Bodies can contain newlines, so split on the 'Row: N' markers (not lines)
    and extract address= up to the next field, body= up to the next ', field='.
    """
    import re
    rows = []
    chunks = re.split(r"Row:\s*\d+\s+", out)
    for chunk in chunks:
        if "address=" not in chunk:
            continue
        addr_m = re.search(r"address=(.*?)(?:,\s*\w+=|$)", chunk, re.DOTALL)
        # body runs until the next ', <field>=' (date/read/etc) or end of chunk
        body_m = re.search(r"body=(.*?)(?:,\s*(?:date|read|date_sent|type|_id|thread_id|service_center)=|$)",
                           chunk, re.DOTALL)
        addr = addr_m.group(1).strip() if addr_m else "?"
        body = body_m.group(1).strip() if body_m else ""
        body = " ".join(body.split())  # collapse newlines/whitespace
        if body and body.lower() != "null":
            rows.append((addr, body[:140]))
        if len(rows) >= limit:
            break
    return rows


def phone_read_sms(count: int = 5) -> str:
    """Read the most recent received SMS messages from the phone."""
    out = _adb("shell", "content", "query", "--uri", "content://sms/inbox",
               "--projection", "address,body,date")
    if out.startswith("adb"):
        return out
    rows = _parse_sms_rows(out, count)
    if not rows:
        return "No SMS found (or permission denied)."
    return "Recent messages:\n" + "\n".join(f"{a}: {b}" for a, b in rows)


def phone_unread_sms() -> str:
    """Read unread SMS messages from the phone."""
    out = _adb("shell", "content", "query", "--uri", "content://sms/inbox",
               "--projection", "address,body,date", "--where", "read=0")
    if out.startswith("adb"):
        return out
    rows = _parse_sms_rows(out, 8)
    if not rows:
        return "No unread messages, Sir."
    n = len(rows)
    return f"{n} unread message" + ("s" if n != 1 else "") + ":\n" + \
           "\n".join(f"{a}: {b}" for a, b in rows)


def phone_call(number: str) -> str:
    """Place a phone call to a number."""
    num = number.strip()
    _adb("shell", "am", "start", "-a", "android.intent.action.CALL",
         "-d", f"tel:{num}")
    return f"Calling {num}, Sir."


SKILLS = [
    ({"name": "phone_status", "description": "Check whether the Android phone is connected via ADB.",
      "parameters": {"type": "object", "properties": {}}}, phone_status),
    ({"name": "phone_open_app",
      "description": "Open an app on the phone by package name (e.g. com.whatsapp, com.android.chrome).",
      "parameters": {"type": "object",
                     "properties": {"package": {"type": "string"}}, "required": ["package"]}}, phone_open_app),
    ({"name": "phone_send_sms",
      "description": "Draft an SMS on the phone to a number with a message body.",
      "parameters": {"type": "object",
                     "properties": {"number": {"type": "string"}, "message": {"type": "string"}},
                     "required": ["number", "message"]}}, phone_send_sms),
    ({"name": "phone_key",
      "description": "Press a hardware/navigation key on the phone.",
      "parameters": {"type": "object",
                     "properties": {"key": {"type": "string", "enum": ["home", "back", "recents", "power"]}},
                     "required": ["key"]}}, phone_key),
    ({"name": "phone_type", "description": "Type text into the focused field on the phone.",
      "parameters": {"type": "object",
                     "properties": {"text": {"type": "string"}}, "required": ["text"]}}, phone_type),
    ({"name": "phone_screenshot", "description": "Take a screenshot on the phone and pull it to the laptop.",
      "parameters": {"type": "object", "properties": {}}}, phone_screenshot),
    ({"name": "phone_notifications", "description": "Read recent notifications from the phone.",
      "parameters": {"type": "object", "properties": {}}}, phone_notifications),
    ({"name": "phone_ring", "description": "Make the phone ring loudly to locate it.",
      "parameters": {"type": "object", "properties": {}}}, phone_ring),
    ({"name": "phone_whatsapp",
      "description": "Open a WhatsApp chat to a number with a prefilled message.",
      "parameters": {"type": "object",
                     "properties": {"number": {"type": "string"}, "message": {"type": "string"}},
                     "required": ["number", "message"]}}, phone_whatsapp),
    ({"name": "phone_read_sms",
      "description": "Read the most recent received SMS text messages from the phone.",
      "parameters": {"type": "object",
                     "properties": {"count": {"type": "integer"}}}}, phone_read_sms),
    ({"name": "phone_unread_sms",
      "description": "Read unread SMS messages from the phone.",
      "parameters": {"type": "object", "properties": {}}}, phone_unread_sms),
    ({"name": "phone_call",
      "description": "Place a phone call to a number from the phone.",
      "parameters": {"type": "object",
                     "properties": {"number": {"type": "string"}}, "required": ["number"]}}, phone_call),
]
