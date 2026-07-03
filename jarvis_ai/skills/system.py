"""Laptop control skills: apps, volume, media keys, info, lock, screenshot, typing."""
import ctypes
import subprocess
import time
from datetime import datetime
from pathlib import Path

import psutil

# Virtual key codes for media / volume keys
VK = {
    "volume_up": 0xAF, "volume_down": 0xAE, "mute": 0xAD,
    "media_play_pause": 0xB3, "media_next": 0xB0, "media_prev": 0xB1,
}


def _tap(vk: int):
    ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
    ctypes.windll.user32.keybd_event(vk, 0, 2, 0)


def open_app(name: str) -> str:
    # `start` resolves registered apps (chrome, notepad, calc, spotify, ...)
    subprocess.Popen(["cmd", "/c", "start", "", name], shell=False)
    return f"Opening {name}."


def close_current_tab(count: int = 1) -> str:
    import pyautogui
    for _ in range(max(1, min(int(count or 1), 10))):
        pyautogui.hotkey("ctrl", "w")
        time.sleep(0.08)
    return "Closed the current tab."


def close_current_window() -> str:
    import pyautogui
    pyautogui.hotkey("alt", "f4")
    return "Closed the current window."


SAFE_KEYS = {
    "win": "Windows",
    "enter": "Enter",
    "esc": "Escape",
    "tab": "Tab",
    "space": "Space",
    "backspace": "Backspace",
    "delete": "Delete",
    "home": "Home",
    "end": "End",
    "pageup": "Page up",
    "pagedown": "Page down",
    "up": "Up arrow",
    "down": "Down arrow",
    "left": "Left arrow",
    "right": "Right arrow",
}

KEY_ALIASES = {
    "windows": "win",
    "window": "win",
    "windows key": "win",
    "windows button": "win",
    "win key": "win",
    "win button": "win",
    "start": "win",
    "start key": "win",
    "start button": "win",
    "start menu": "win",
    "escape": "esc",
    "escape key": "esc",
    "enter key": "enter",
    "return": "enter",
    "return key": "enter",
    "spacebar": "space",
    "space bar": "space",
    "page up": "pageup",
    "page down": "pagedown",
    "up arrow": "up",
    "down arrow": "down",
    "left arrow": "left",
    "right arrow": "right",
}


def press_key(key: str) -> str:
    import pyautogui
    raw = (key or "").strip().lower()
    mapped = KEY_ALIASES.get(raw, raw)
    if mapped not in SAFE_KEYS:
        return f"I cannot press {key} without a safe local route."
    pyautogui.press(mapped)
    return f"Pressed {SAFE_KEYS[mapped]} key."


def close_app(name: str) -> str:
    """Close an app by common name. Browser names close the whole browser."""
    aliases = {
        "chrome": "chrome.exe",
        "google chrome": "chrome.exe",
        "edge": "msedge.exe",
        "microsoft edge": "msedge.exe",
        "youtube": "chrome.exe",
        "notepad": "notepad.exe",
        "calculator": "CalculatorApp.exe",
        "calc": "CalculatorApp.exe",
        "spotify": "Spotify.exe",
    }
    exe = aliases.get((name or "").strip().lower())
    if not exe:
        exe = name if name.lower().endswith(".exe") else f"{name}.exe"
    try:
        subprocess.run(["taskkill", "/IM", exe, "/T", "/F"], capture_output=True, text=True, timeout=10)
        return f"Closed {name}."
    except Exception as e:
        return f"Could not close {name}: {e}"


def set_volume(direction: str, steps: int = 5) -> str:
    vk = VK.get("volume_" + direction)
    if not vk:
        return "Direction must be 'up' or 'down'."
    for _ in range(max(1, steps)):
        _tap(vk)
    return f"Volume {direction}."


def mute() -> str:
    _tap(VK["mute"])
    return "Toggled mute."


def system_info() -> str:
    batt = psutil.sensors_battery()
    if batt:
        state = "charging" if batt.power_plugged else "on battery"
        batt_s = f"battery {batt.percent}% {state}"
    else:
        batt_s = "no battery sensor"
    return (f"CPU {psutil.cpu_percent(interval=0.3)}%, "
            f"RAM {psutil.virtual_memory().percent}%, {batt_s}.")


def lock_pc() -> str:
    ctypes.windll.user32.LockWorkStation()
    return "Locking the laptop."


def take_screenshot() -> str:
    import pyautogui
    path = Path.home() / "Pictures" / f"jarvis_{int(time.time())}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    pyautogui.screenshot(str(path))
    return f"Screenshot saved to {path}."


def type_text(text: str) -> str:
    import pyautogui
    pyautogui.typewrite(text, interval=0.01)
    return "Typed."


def tell_time() -> str:
    return datetime.now().strftime("It is %I:%M %p on %A, %d %B.")


SKILLS = [
    ({"name": "open_app",
      "description": "Open/launch an application on the laptop by name (e.g. chrome, notepad, calc, spotify).",
      "parameters": {"type": "object",
                     "properties": {"name": {"type": "string", "description": "App name"}},
                     "required": ["name"]}}, open_app),
    ({"name": "close_current_tab",
      "description": "Close the active browser/editor tab using Ctrl+W.",
      "parameters": {"type": "object",
                     "properties": {"count": {"type": "integer", "description": "Number of tabs to close"}}}}, close_current_tab),
    ({"name": "close_current_window",
      "description": "Close the active app/window using Alt+F4.",
      "parameters": {"type": "object", "properties": {}}}, close_current_window),
    ({"name": "press_key",
      "description": "Press a safe keyboard key such as Windows, Enter, Escape, Tab, Space, arrows, Delete, Home, or End.",
      "parameters": {"type": "object",
                     "properties": {"key": {"type": "string"}},
                     "required": ["key"]}}, press_key),
    ({"name": "close_app",
      "description": "Close an app by name, such as chrome, edge, notepad, calculator, spotify.",
      "parameters": {"type": "object",
                     "properties": {"name": {"type": "string"}},
                     "required": ["name"]}}, close_app),
    ({"name": "set_volume",
      "description": "Raise or lower the laptop volume.",
      "parameters": {"type": "object",
                     "properties": {"direction": {"type": "string", "enum": ["up", "down"]},
                                    "steps": {"type": "integer", "description": "How many steps (default 5)"}},
                     "required": ["direction"]}}, set_volume),
    ({"name": "mute", "description": "Toggle system mute.",
      "parameters": {"type": "object", "properties": {}}}, mute),
    ({"name": "system_info", "description": "Report CPU, RAM and battery status.",
      "parameters": {"type": "object", "properties": {}}}, system_info),
    ({"name": "lock_pc", "description": "Lock the Windows session.",
      "parameters": {"type": "object", "properties": {}}}, lock_pc),
    ({"name": "take_screenshot", "description": "Capture the screen to the Pictures folder.",
      "parameters": {"type": "object", "properties": {}}}, take_screenshot),
    ({"name": "type_text", "description": "Type text into the currently focused window.",
      "parameters": {"type": "object",
                     "properties": {"text": {"type": "string"}}, "required": ["text"]}}, type_text),
    ({"name": "tell_time", "description": "Tell the current time and date.",
      "parameters": {"type": "object", "properties": {}}}, tell_time),
]
