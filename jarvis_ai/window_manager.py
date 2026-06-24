"""Windows process/window discovery.

Lists all visible windows with titles and PIDs.  Resolves app names to
window handles for precise targeting by the system/desktop skills.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
from dataclasses import dataclass


@dataclass
class WindowInfo:
    """Information about a single visible window."""
    hwnd: int
    title: str
    pid: int
    is_visible: bool


# Win32 API typedefs for window enumeration
_EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32


def _get_window_pid(hwnd: int) -> int:
    """Get the process ID owning a window handle."""
    pid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _get_window_title(hwnd: int) -> str:
    """Get the title text of a window handle."""
    length = _user32.GetWindowTextLengthW(hwnd)
    if length == 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    _user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def list_windows(visible_only: bool = True) -> list[WindowInfo]:
    """Enumerate all (or all visible) top-level windows.

    Returns a list of WindowInfo sorted by title.
    """
    windows: list[WindowInfo] = []

    def _callback(hwnd, _lparam):
        if visible_only:
            if not _user32.IsWindowVisible(hwnd):
                return True
        title = _get_window_title(hwnd)
        if not title:
            return True
        pid = _get_window_pid(hwnd)
        windows.append(WindowInfo(
            hwnd=hwnd, title=title, pid=pid,
            is_visible=bool(_user32.IsWindowVisible(hwnd)),
        ))
        return True

    _user32.EnumWindows(_EnumWindowsProc(_callback), 0)

    windows.sort(key=lambda w: w.title.lower())
    return windows


def find_window_by_title(query: str) -> WindowInfo | None:
    """Find a window whose title contains *query* (case-insensitive)."""
    query_lower = query.lower()
    for w in list_windows():
        if query_lower in w.title.lower():
            return w
    return None


def find_windows_by_pid(pid: int) -> list[WindowInfo]:
    """Find all windows owned by *pid*."""
    return [w for w in list_windows() if w.pid == pid]


def get_process_name(pid: int) -> str:
    """Get the executable name for a PID using a query handle."""
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(260)
        size = wintypes.DWORD(260)
        if _kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value
        return ""
    finally:
        _kernel32.CloseHandle(handle)


def list_apps() -> list[dict]:
    """List running applications with windows.

    Returns a list of dicts: ``{title, pid, exe}``.
    """
    seen_pids: set[int] = set()
    apps: list[dict] = []
    for w in list_windows():
        if w.pid in seen_pids:
            continue
        seen_pids.add(w.pid)
        exe = ""
        try:
            exe = get_process_name(w.pid)
        except Exception:
            pass
        apps.append({"title": w.title, "pid": w.pid, "exe": exe})
    return apps
