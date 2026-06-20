"""Full Windows system control — power, processes, windows, network, display, settings."""
import subprocess
import ctypes
import os
from pathlib import Path


# ── Helpers ─────────────────────────────────────────────────────────

def _ps(cmd: str, timeout: int = 10) -> str:
    """Run a PowerShell one-liner, return stdout stripped."""
    r = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
        capture_output=True, text=True, timeout=timeout,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    out = (r.stdout or "").strip()
    err = (r.stderr or "").strip()
    return out if out else (err[:120] if err else "Done.")


# ── Power / session ──────────────────────────────────────────────────

def sleep_pc() -> str:
    subprocess.Popen(
        ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return "Sleeping now, Sir."


def hibernate_pc() -> str:
    subprocess.Popen(
        ["shutdown", "/h"],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return "Hibernating, Sir."


def restart_pc() -> str:
    subprocess.Popen(
        ["shutdown", "/r", "/t", "5", "/c", "Leha restarting."],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return "Restarting in 5 seconds, Sir."


def shutdown_pc() -> str:
    subprocess.Popen(
        ["shutdown", "/s", "/t", "5", "/c", "Leha shutting down."],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return "Shutting down in 5 seconds, Sir."


def logoff_pc() -> str:
    subprocess.Popen(
        ["shutdown", "/l"],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return "Logging off, Sir."


# ── Process management ───────────────────────────────────────────────

def get_processes(count: int = 5) -> str:
    n = min(max(int(count or 5), 1), 20)
    out = _ps(
        f"Get-Process | Sort-Object CPU -Descending | "
        f"Select-Object -First {n} Name,CPU,WorkingSet | "
        f"Format-Table -HideTableHeaders | Out-String"
    )
    return out or "No processes found."


def kill_process(name: str) -> str:
    safe = name.replace('"', '').replace("'", "").strip()
    out = _ps(
        f'$p = Get-Process -Name "{safe}" -ErrorAction SilentlyContinue; '
        f'if ($p) {{ $p | Stop-Process -Force; "Killed {safe}." }} '
        f'else {{ "No process named {safe} found." }}'
    )
    return out


# ── Window management ────────────────────────────────────────────────

def show_desktop() -> str:
    import pyautogui
    pyautogui.hotkey("win", "d")
    return "Showing desktop, Sir."


def minimize_all() -> str:
    import pyautogui
    pyautogui.hotkey("win", "m")
    return "Minimized all windows, Sir."


def snap_window(direction: str = "left") -> str:
    import pyautogui
    d = direction.lower().strip()
    mapping = {
        "left": ("win", "left"),
        "right": ("win", "right"),
        "up": ("win", "up"),
        "maximize": ("win", "up"),
        "down": ("win", "down"),
        "minimize": ("win", "down"),
        "fullscreen": ("win", "up"),
    }
    keys = mapping.get(d, ("win", "left"))
    pyautogui.hotkey(*keys)
    return f"Snapped window {d}, Sir."


def switch_to_app(name: str) -> str:
    safe = name.strip()
    out = _ps(
        f'$h = (Get-Process -Name "{safe}" -ErrorAction SilentlyContinue | '
        f'Where-Object {{$_.MainWindowHandle -ne 0}} | Select-Object -First 1).MainWindowHandle; '
        f'if ($h) {{ '
        f'Add-Type -TypeDefinition \'using System; using System.Runtime.InteropServices; '
        f'public class W {{[DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);}}\'; '
        f'[W]::SetForegroundWindow($h); "Switched to {safe}." }} '
        f'else {{ "Cannot find {safe} window." }}'
    )
    return out


# ── Display ──────────────────────────────────────────────────────────

def set_brightness(percent: int = 50) -> str:
    v = max(0, min(int(percent or 50), 100))
    out = _ps(
        f'$b = Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods; '
        f'if ($b) {{ $b.WmiSetBrightness(1, {v}); "Brightness set to {v}%." }} '
        f'else {{ "Brightness control not available on this monitor." }}'
    )
    return out


def turn_off_screen() -> str:
    _ps(
        'Add-Type -TypeDefinition \'using System; using System.Runtime.InteropServices; '
        'public class S {[DllImport("user32.dll")] public static extern IntPtr '
        'SendMessage(IntPtr hWnd, uint m, IntPtr w, IntPtr l);}\'; '
        '[S]::SendMessage([IntPtr]0xFFFF, 0x0112, [IntPtr]0xF170, [IntPtr]2)'
    )
    return "Screen off, Sir."


def eject_usb(drive_letter: str = "E") -> str:
    letter = drive_letter.strip().rstrip(":").upper()
    out = _ps(
        f'$s = (New-Object -ComObject Shell.Application).NameSpace(17); '
        f'$d = $s.Items() | Where-Object {{$_.Path -like "{letter}:*"}} | Select-Object -First 1; '
        f'if ($d) {{ $d.InvokeVerb("Eject"); "Ejected {letter}:." }} '
        f'else {{ "Drive {letter}: not found." }}'
    )
    return out


# ── Network ──────────────────────────────────────────────────────────

def get_ip() -> str:
    out = _ps(
        "(Get-NetIPAddress -AddressFamily IPv4 | "
        "Where-Object {$_.IPAddress -ne '127.0.0.1'} | "
        "Select-Object -First 1).IPAddress"
    )
    return f"IP address: {out}" if out else "Could not get IP."


def toggle_wifi(state: str = "toggle") -> str:
    s = state.lower().strip()
    if s in {"off", "disable", "turn off"}:
        _ps('netsh interface set interface "Wi-Fi" admin=disabled')
        return "Wi-Fi disabled, Sir."
    elif s in {"on", "enable", "turn on"}:
        _ps('netsh interface set interface "Wi-Fi" admin=enabled')
        return "Wi-Fi enabled, Sir."
    else:
        # toggle based on current state
        status = _ps('(Get-NetAdapter -Name "Wi-Fi" -ErrorAction SilentlyContinue).Status')
        if "Up" in status:
            _ps('netsh interface set interface "Wi-Fi" admin=disabled')
            return "Wi-Fi turned off, Sir."
        else:
            _ps('netsh interface set interface "Wi-Fi" admin=enabled')
            return "Wi-Fi turned on, Sir."


def list_wifi() -> str:
    out = _ps("netsh wlan show networks | Select-String 'SSID' | Select-Object -First 10")
    return out or "No Wi-Fi networks found."


# ── System settings ───────────────────────────────────────────────────

def dark_mode(enable: bool = True) -> str:
    val = 0 if enable else 1
    _ps(
        f'Set-ItemProperty -Path "HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize" '
        f'-Name AppsUseLightTheme -Value {val}; '
        f'Set-ItemProperty -Path "HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize" '
        f'-Name SystemUsesLightTheme -Value {val}'
    )
    return f"{'Dark' if enable else 'Light'} mode enabled, Sir."


def set_wallpaper(path: str) -> str:
    p = str(Path(path).resolve())
    if not os.path.exists(p):
        return f"File not found: {p}"
    SPI_SETDESKWALLPAPER = 20
    ctypes.windll.user32.SystemParametersInfoW(SPI_SETDESKWALLPAPER, 0, p, 3)
    return f"Wallpaper set to {p}, Sir."


def battery_report() -> str:
    out = _ps(
        'powercfg /batteryreport /output "$env:TEMP\\battery.html" 2>&1; '
        'Start-Process "$env:TEMP\\battery.html"; "Battery report opened."'
    )
    return out


def find_large_files(min_gb: float = 1.0, folder: str = "C:\\") -> str:
    min_bytes = int(float(min_gb) * 1024**3)
    out = _ps(
        f'Get-ChildItem -Path "{folder}" -Recurse -ErrorAction SilentlyContinue '
        f'| Where-Object {{$_.Length -gt {min_bytes}}} '
        f'| Sort-Object Length -Descending '
        f'| Select-Object -First 5 FullName,@{{N="GB";E={{[math]::Round($_.Length/1GB,1)}}}} '
        f'| Format-Table -HideTableHeaders | Out-String',
        timeout=30,
    )
    return out or f"No files larger than {min_gb}GB found in {folder}."


# ── SKILLS registry ───────────────────────────────────────────────────

SKILLS = [
    ({"name": "sleep_pc", "description": "Put the laptop to sleep/suspend.",
      "parameters": {"type": "object", "properties": {}}}, sleep_pc),

    ({"name": "hibernate_pc", "description": "Hibernate the laptop.",
      "parameters": {"type": "object", "properties": {}}}, hibernate_pc),

    ({"name": "restart_pc", "description": "Restart the laptop (5s delay).",
      "parameters": {"type": "object", "properties": {}}}, restart_pc),

    ({"name": "shutdown_pc", "description": "Shut down the laptop (5s delay).",
      "parameters": {"type": "object", "properties": {}}}, shutdown_pc),

    ({"name": "logoff_pc", "description": "Log off the current Windows user.",
      "parameters": {"type": "object", "properties": {}}}, logoff_pc),

    ({"name": "get_processes",
      "description": "List top N running processes by CPU usage.",
      "parameters": {"type": "object", "properties": {
          "count": {"type": "integer", "description": "How many to show (default 5)"}
      }}}, get_processes),

    ({"name": "kill_process",
      "description": "Kill a running process by name.",
      "parameters": {"type": "object", "properties": {
          "name": {"type": "string", "description": "Process name e.g. chrome, notepad"}
      }, "required": ["name"]}}, kill_process),

    ({"name": "show_desktop", "description": "Show the desktop (Win+D).",
      "parameters": {"type": "object", "properties": {}}}, show_desktop),

    ({"name": "minimize_all", "description": "Minimize all open windows.",
      "parameters": {"type": "object", "properties": {}}}, minimize_all),

    ({"name": "snap_window",
      "description": "Snap active window to left, right, maximize, or minimize.",
      "parameters": {"type": "object", "properties": {
          "direction": {"type": "string",
                        "enum": ["left", "right", "up", "down", "maximize", "minimize"],
                        "description": "Direction to snap"}
      }}}, snap_window),

    ({"name": "switch_to_app",
      "description": "Bring a running app window to the foreground.",
      "parameters": {"type": "object", "properties": {
          "name": {"type": "string", "description": "Process name e.g. chrome, code, notepad"}
      }, "required": ["name"]}}, switch_to_app),

    ({"name": "set_brightness",
      "description": "Set screen brightness percentage (0-100).",
      "parameters": {"type": "object", "properties": {
          "percent": {"type": "integer", "description": "Brightness 0-100"}
      }, "required": ["percent"]}}, set_brightness),

    ({"name": "turn_off_screen", "description": "Turn off the screen/monitor.",
      "parameters": {"type": "object", "properties": {}}}, turn_off_screen),

    ({"name": "eject_usb",
      "description": "Safely eject a USB drive by drive letter.",
      "parameters": {"type": "object", "properties": {
          "drive_letter": {"type": "string", "description": "Drive letter e.g. E, F"}
      }}}, eject_usb),

    ({"name": "get_ip", "description": "Get this laptop's local IP address.",
      "parameters": {"type": "object", "properties": {}}}, get_ip),

    ({"name": "toggle_wifi",
      "description": "Turn Wi-Fi on or off, or toggle it.",
      "parameters": {"type": "object", "properties": {
          "state": {"type": "string", "enum": ["on", "off", "toggle"],
                    "description": "on/off/toggle"}
      }}}, toggle_wifi),

    ({"name": "list_wifi", "description": "List nearby Wi-Fi networks.",
      "parameters": {"type": "object", "properties": {}}}, list_wifi),

    ({"name": "dark_mode",
      "description": "Switch Windows to dark mode or light mode.",
      "parameters": {"type": "object", "properties": {
          "enable": {"type": "boolean", "description": "True=dark, False=light"}
      }}}, dark_mode),

    ({"name": "set_wallpaper",
      "description": "Change the desktop wallpaper to an image file.",
      "parameters": {"type": "object", "properties": {
          "path": {"type": "string", "description": "Full path to image file"}
      }, "required": ["path"]}}, set_wallpaper),

    ({"name": "battery_report",
      "description": "Generate and open a detailed battery health report.",
      "parameters": {"type": "object", "properties": {}}}, battery_report),

    ({"name": "find_large_files",
      "description": "Find files larger than N GB on a drive.",
      "parameters": {"type": "object", "properties": {
          "min_gb": {"type": "number", "description": "Minimum size in GB (default 1)"},
          "folder": {"type": "string", "description": "Folder to search (default C:\\)"}
      }}}, find_large_files),
]
