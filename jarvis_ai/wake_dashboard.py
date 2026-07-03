"""System tray dashboard for Leha.

Shows mic state, wake engine, last wake time, turn count in a tray icon.
Click → shows health summary. Right-click → menu with health, restart, quit.

Requires: ``pip install pystray Pillow``

Usage:
    python -m jarvis_ai.wake_dashboard
"""
from __future__ import annotations

import threading
import time
import subprocess
import webbrowser
from pathlib import Path


def _try_import():
    """Gracefully handle missing pystray."""
    try:
        import pystray
        from PIL import Image, ImageDraw, ImageFont
        return pystray, Image, ImageDraw, ImageFont
    except ImportError:
        return None, None, None, None


def _create_icon(color: str = "#22D3EE") -> "Image.Image | None":
    """Create a simple L-shaped icon."""
    _, Image, ImageDraw, _ = _try_import()
    if Image is None:
        return None
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([8, 8, 56, 56], radius=12, fill=color)
    draw.text((16, 20), "L", fill="white")
    return img


def _health_text() -> str:
    """Get health summary for tooltip."""
    try:
        from jarvis_ai.health import voice_summary
        return voice_summary()
    except Exception:
        return "Leha"


def _run_script_file(name: str) -> None:
    root = Path(__file__).resolve().parent.parent
    script = root / "scripts" / name
    if not script.exists():
        raise FileNotFoundError(f"Missing script: {name}")
    subprocess.Popen(
        ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(script)],
        cwd=str(root),
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def _state_icon(state: str) -> "Image.Image | None":
    """Return icon color based on state."""
    colors = {
        "idle": "#22D3EE",
        "listening": "#34D399",
        "transcribing": "#FBBF24",
        "thinking": "#A78BFA",
        "speaking": "#F472B6",
        "error": "#EF4444",
    }
    color = colors.get(state, "#22D3EE")
    return _create_icon(color)


def main():
    pystray = _try_import()[0]
    if pystray is None:
        print("[dashboard] Install pystray: pip install pystray Pillow")
        return

    from jarvis_ai import runtime_state, config

    state = {"icon": None, "running": True}

    def _on_clicked(icon, item):
        text = _health_text()
        from pystray import Menu, MenuItem
        icon.notify(text, "Leha Health")

    def _run_script(name: str):
        try:
            _run_script_file(name)
            icon.notify(f"Started {name}", "Leha")
        except Exception as e:
            icon.notify(str(e), "Leha")

    def _open_dashboard(icon, item):
        webbrowser.open("http://127.0.0.1:8001/dashboard")

    def _start_listener(icon, item):
        _run_script("start_leha.ps1")

    def _restart_listener(icon, item):
        _run_script("restart_leha.ps1")

    def _stop_listener(icon, item):
        _run_script("stop_leha.ps1")

    def _status(icon, item):
        _run_script("status_leha.ps1")

    def _validate(icon, item):
        _run_script("validate_startup.ps1")

    def _install_startup(icon, item):
        _run_script("install_autostart.ps1")

    def _uninstall_startup(icon, item):
        _run_script("uninstall_autostart.ps1")

    def _cleanup_logs(icon, item):
        _run_script("cleanup_logs.ps1")

    def _on_quit(icon, item):
        state["running"] = False
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Health", _on_clicked, default=True),
        pystray.MenuItem("Open Dashboard", _open_dashboard),
        pystray.MenuItem("Status", _status),
        pystray.MenuItem("Validate Startup", _validate),
        pystray.MenuItem("Start Listener", _start_listener),
        pystray.MenuItem("Restart Listener", _restart_listener),
        pystray.MenuItem("Stop Listener", _stop_listener),
        pystray.MenuItem("Install Startup", _install_startup),
        pystray.MenuItem("Uninstall Startup", _uninstall_startup),
        pystray.MenuItem("Cleanup Logs", _cleanup_logs),
        pystray.MenuItem("Quit Tray", _on_quit),
    )

    icon = pystray.Icon("leha", _create_icon(), "Leha", menu)

    # Background thread to update icon based on runtime state
    def _updater():
        last_state = ""
        while state["running"]:
            try:
                snap = runtime_state.runtime.snapshot()
                current = snap.get("state", "idle")
                if current != last_state:
                    last_state = current
                    new_icon = _state_icon(current)
                    if new_icon:
                        icon.icon = new_icon
                    turns = snap.get("turns", 0)
                    provider = snap.get("last_provider", "local")
                    icon.title = f"Leha | {current} | {turns} turns | {provider}"
            except Exception:
                pass
            time.sleep(2)

    updater_thread = threading.Thread(target=_updater, daemon=True)
    updater_thread.start()

    print("[dashboard] Tray icon started")
    try:
        icon.run()
    except KeyboardInterrupt:
        pass
    print("[dashboard] Stopped")


if __name__ == "__main__":
    main()
