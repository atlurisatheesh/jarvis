"""Android control skills via ADB (Phase 5).

Requires: USB debugging enabled on the phone, adb on PATH (or set ADB_PATH),
and the phone connected by USB or 'adb connect <ip>' over WiFi.
"""
import subprocess
import time
import re
import urllib.parse
import xml.etree.ElementTree as ET

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


def _connected_devices() -> list[str]:
    out = _adb("devices")
    devices = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            devices.append(parts[0])
    return devices


def _prop(name: str) -> str:
    out = _adb("shell", "getprop", name, timeout=8)
    return out.strip() if out and not out.lower().startswith("adb ") else ""


def _battery_summary() -> str:
    out = _adb("shell", "dumpsys", "battery", timeout=8)
    level = re.search(r"\blevel:\s*(\d+)", out)
    usb = re.search(r"\bUSB powered:\s*(true|false)", out, re.I)
    ac = re.search(r"\bAC powered:\s*(true|false)", out, re.I)
    parts = []
    if level:
        parts.append(f"{level.group(1)}%")
    charging = []
    if usb and usb.group(1).lower() == "true":
        charging.append("USB")
    if ac and ac.group(1).lower() == "true":
        charging.append("AC")
    if charging:
        parts.append("charging via " + "/".join(charging))
    return ", ".join(parts) if parts else "battery unknown"


def phone_status() -> str:
    devices = _connected_devices()
    if not devices:
        return "No Android phone detected. Check USB debugging and ADB authorization."
    model = _prop("ro.product.model") or "Android phone"
    android = _prop("ro.build.version.release") or "unknown Android"
    battery = _battery_summary()
    connection = "wireless ADB" if ":5555" in devices[0] else "USB ADB"
    return f"Phone connected: {model}, Android {android}, {battery}, {connection}."


def phone_wifi_setup(ip: str = "") -> str:
    """Switch the USB-connected phone to wireless ADB so it works untethered.

    One time: phone plugged via USB, same Wi-Fi as laptop. This puts adb in
    TCP mode and connects over Wi-Fi; afterwards the USB cable can be removed.
    Auto-detects the phone IP if not given.
    """
    # 1) get phone IP if not provided
    if not _connected_devices():
        return "Connect the phone by USB and allow USB debugging before wireless setup."
    if not ip:
        out = _adb("shell", "ip", "-f", "inet", "addr", "show", "wlan0")
        m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", out)
        if not m:
            return ("Plug the phone via USB first and ensure Wi-Fi is on. "
                    "Could not read phone IP.")
        ip = m.group(1)
    # 2) restart adb in TCP mode
    _adb("tcpip", "5555", timeout=15)
    time.sleep(1.5)
    # 3) connect over Wi-Fi
    res = _adb("connect", f"{ip}:5555", timeout=15)
    low = res.lower()
    if "connected" in low or "already connected" in low:
        try:
            (config.BASE_DIR.parent / ".phone_ip").write_text(f"{ip}:5555",
                                                              encoding="utf-8")
        except Exception:
            pass
        return f"Phone is now wireless at {ip}. You can unplug the cable, Sir."
    return f"Wi-Fi connect result: {res}"


def phone_wifi_reconnect() -> str:
    """Reconnect to the last-known wireless phone (after laptop/phone restart)."""
    f = config.BASE_DIR.parent / ".phone_ip"
    if not f.exists():
        return "No saved phone Wi-Fi address. Run wifi setup once over USB first."
    addr = f.read_text(encoding="utf-8").strip()
    res = _adb("connect", addr, timeout=15)
    return f"Reconnect {addr}: {res}"


def phone_open_url(url: str) -> str:
    target = (url or "").strip()
    if not target:
        return "No URL provided."
    if "://" not in target:
        target = "https://" + target
    _adb("shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", target)
    return f"Opening {target} on the phone."


def phone_open_app(package: str) -> str:
    _adb("shell", "monkey", "-p", package,
         "-c", "android.intent.category.LAUNCHER", "1")
    return f"Opening {package} on the phone."


def phone_force_stop_app(package: str) -> str:
    pkg = (package or "").strip()
    if not pkg:
        return "No Android package provided."
    _adb("shell", "am", "force-stop", pkg)
    return f"Closed {pkg} on the phone."


def phone_youtube_search(query: str) -> str:
    q = (query or "").strip()
    if not q:
        return "No YouTube search query provided."
    url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(q)
    return phone_open_url(url)


def phone_maps(destination: str) -> str:
    dest = (destination or "").strip()
    if not dest:
        return "No destination provided."
    url = "google.navigation:q=" + urllib.parse.quote_plus(dest)
    _adb("shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", url)
    return f"Opening navigation to {dest} on the phone."


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


def phone_tap(x: int, y: int) -> str:
    _adb("shell", "input", "tap", str(int(x)), str(int(y)))
    return f"Tapped phone at {int(x)}, {int(y)}."


def phone_swipe(x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> str:
    duration = max(50, min(3000, int(duration_ms)))
    _adb("shell", "input", "swipe", str(int(x1)), str(int(y1)), str(int(x2)), str(int(y2)), str(duration))
    return "Swiped on the phone."


def phone_screenshot() -> str:
    remote = "/sdcard/jarvis_shot.png"
    _adb("shell", "screencap", "-p", remote)
    local = f"phone_shot_{int(time.time())}.png"
    _adb("pull", remote, local)
    return f"Phone screenshot saved to {local}."


def phone_screen_dump() -> str:
    """Dump visible Android UI text and clickable element bounds."""
    remote = "/sdcard/window_dump.xml"
    _adb("shell", "uiautomator", "dump", remote, timeout=15)
    xml = _adb("shell", "cat", remote, timeout=15)
    if not xml or xml.lower().startswith("adb "):
        return "Could not read phone screen. Unlock the phone and try again."
    items = []
    try:
        root = ET.fromstring(xml)
        for node in root.iter("node"):
            text = (node.attrib.get("text") or "").strip()
            desc = (node.attrib.get("content-desc") or "").strip()
            label = text or desc
            if not label:
                continue
            bounds = node.attrib.get("bounds", "")
            clickable = node.attrib.get("clickable", "false")
            items.append((label[:80], bounds, clickable))
            if len(items) >= 12:
                break
    except ET.ParseError:
        return "Could not parse the phone screen."
    if not items:
        return "No readable phone screen text. Unlock the phone or open an app."
    lines = []
    for label, bounds, clickable in items:
        suffix = " clickable" if clickable == "true" else ""
        lines.append(f"{label} {bounds}{suffix}".strip())
    return "Phone screen:\n" + "\n".join(lines)


def phone_tap_text(text: str) -> str:
    """Tap the center of the first visible UI node matching text/description."""
    target = (text or "").strip().lower()
    if not target:
        return "No text provided to tap."
    remote = "/sdcard/window_dump.xml"
    _adb("shell", "uiautomator", "dump", remote, timeout=15)
    xml = _adb("shell", "cat", remote, timeout=15)
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return "Could not parse the phone screen."
    for node in root.iter("node"):
        label = ((node.attrib.get("text") or "") + " " + (node.attrib.get("content-desc") or "")).strip().lower()
        if target not in label:
            continue
        bounds = node.attrib.get("bounds", "")
        nums = [int(n) for n in re.findall(r"\d+", bounds)]
        if len(nums) == 4:
            x = (nums[0] + nums[2]) // 2
            y = (nums[1] + nums[3]) // 2
            _adb("shell", "input", "tap", str(x), str(y))
            return f"Tapped {text} on the phone."
    return f"I could not find {text} on the phone screen."


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
    ({"name": "phone_force_stop_app",
      "description": "Close an app on the phone by Android package name.",
      "parameters": {"type": "object",
                     "properties": {"package": {"type": "string"}}, "required": ["package"]}}, phone_force_stop_app),
    ({"name": "phone_open_url",
      "description": "Open a URL on the phone.",
      "parameters": {"type": "object",
                     "properties": {"url": {"type": "string"}}, "required": ["url"]}}, phone_open_url),
    ({"name": "phone_youtube_search",
      "description": "Search YouTube on the phone.",
      "parameters": {"type": "object",
                     "properties": {"query": {"type": "string"}}, "required": ["query"]}}, phone_youtube_search),
    ({"name": "phone_maps",
      "description": "Open Google Maps navigation on the phone.",
      "parameters": {"type": "object",
                     "properties": {"destination": {"type": "string"}}, "required": ["destination"]}}, phone_maps),
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
    ({"name": "phone_tap", "description": "Tap absolute coordinates on the phone screen.",
      "parameters": {"type": "object",
                     "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}},
                     "required": ["x", "y"]}}, phone_tap),
    ({"name": "phone_swipe", "description": "Swipe absolute coordinates on the phone screen.",
      "parameters": {"type": "object",
                     "properties": {
                         "x1": {"type": "integer"}, "y1": {"type": "integer"},
                         "x2": {"type": "integer"}, "y2": {"type": "integer"},
                         "duration_ms": {"type": "integer"}},
                     "required": ["x1", "y1", "x2", "y2"]}}, phone_swipe),
    ({"name": "phone_screenshot", "description": "Take a screenshot on the phone and pull it to the laptop.",
      "parameters": {"type": "object", "properties": {}}}, phone_screenshot),
    ({"name": "phone_screen_dump", "description": "Read visible phone screen text and clickable bounds.",
      "parameters": {"type": "object", "properties": {}}}, phone_screen_dump),
    ({"name": "phone_tap_text", "description": "Tap the first visible phone UI item matching text.",
      "parameters": {"type": "object",
                     "properties": {"text": {"type": "string"}}, "required": ["text"]}}, phone_tap_text),
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
    ({"name": "phone_wifi_setup",
      "description": "Make the USB-connected phone work wirelessly over Wi-Fi (untether). "
                     "Run once with the cable plugged in.",
      "parameters": {"type": "object",
                     "properties": {"ip": {"type": "string", "description": "Phone IP (auto if blank)"}}}},
     phone_wifi_setup),
    ({"name": "phone_wifi_reconnect",
      "description": "Reconnect to the last wireless phone after a restart.",
      "parameters": {"type": "object", "properties": {}}}, phone_wifi_reconnect),
]
