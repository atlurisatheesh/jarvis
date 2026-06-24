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
    Image = _try_import()[1]
    if Image is None:
        return None
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = Image.ImageDraw.Draw(img)
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

    def _on_quit(icon, item):
        state["running"] = False
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Health", _on_clicked, default=True),
        pystray.MenuItem("Quit", _on_quit),
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
