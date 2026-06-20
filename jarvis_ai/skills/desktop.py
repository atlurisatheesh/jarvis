"""Advanced desktop skills: screen OCR, clipboard, organize downloads, run script."""
import os
import shutil
import subprocess
from pathlib import Path

from .. import config


def read_screen() -> str:
    """Screenshot the screen and OCR it to text (needs Tesseract installed)."""
    try:
        import pyautogui
        import pytesseract
        if config.TESSERACT_PATH:
            pytesseract.pytesseract.tesseract_cmd = config.TESSERACT_PATH
        img = pyautogui.screenshot()
        text = pytesseract.image_to_string(img).strip()
        return text[:1500] if text else "No readable text on screen."
    except Exception as e:
        return f"OCR unavailable: {e}. Install Tesseract and set TESSERACT_PATH."


def read_clipboard() -> str:
    try:
        import pyperclip
        return pyperclip.paste() or "Clipboard is empty."
    except Exception as e:
        return f"Clipboard error: {e}"


def set_clipboard(text: str) -> str:
    try:
        import pyperclip
        pyperclip.copy(text)
        return "Copied to clipboard."
    except Exception as e:
        return f"Clipboard error: {e}"


def organize_downloads() -> str:
    dl = Path.home() / "Downloads"
    if not dl.exists():
        return "No Downloads folder."
    buckets = {
        "Images": {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"},
        "Docs": {".pdf", ".docx", ".doc", ".txt", ".md", ".xlsx", ".pptx"},
        "Archives": {".zip", ".rar", ".7z", ".tar", ".gz"},
        "Installers": {".exe", ".msi"},
        "Media": {".mp4", ".mp3", ".wav", ".mkv", ".mov"},
    }
    moved = 0
    for f in dl.iterdir():
        if not f.is_file():
            continue
        for folder, exts in buckets.items():
            if f.suffix.lower() in exts:
                dest = dl / folder
                dest.mkdir(exist_ok=True)
                try:
                    shutil.move(str(f), str(dest / f.name))
                    moved += 1
                except Exception:
                    pass
                break
    return f"Organized {moved} files in Downloads."


def run_script(path: str) -> str:
    """Run a whitelisted local script. Only paths under SCRIPT_DIR are allowed."""
    p = Path(os.path.expanduser(path)).resolve()
    allowed = Path(config.SCRIPT_DIR).resolve()
    if config.SCRIPT_DIR and allowed not in p.parents and p != allowed:
        return f"Refused: only scripts under {allowed} may run."
    if not p.exists():
        return f"Script not found: {p}"
    try:
        r = subprocess.run(["python", str(p)], capture_output=True, text=True, timeout=120)
        return (r.stdout or r.stderr or "done").strip()[:1000]
    except Exception as e:
        return f"Run error: {e}"


SKILLS = [
    ({"name": "read_screen", "description": "Read text currently visible on the screen via OCR.",
      "parameters": {"type": "object", "properties": {}}}, read_screen),
    ({"name": "read_clipboard", "description": "Read the current clipboard contents.",
      "parameters": {"type": "object", "properties": {}}}, read_clipboard),
    ({"name": "set_clipboard", "description": "Put text on the clipboard.",
      "parameters": {"type": "object",
                     "properties": {"text": {"type": "string"}}, "required": ["text"]}}, set_clipboard),
    ({"name": "organize_downloads", "description": "Tidy the Downloads folder into subfolders by file type.",
      "parameters": {"type": "object", "properties": {}}}, organize_downloads),
    ({"name": "run_script",
      "description": "Run a local Python script (only allowed under the configured script directory).",
      "parameters": {"type": "object",
                     "properties": {"path": {"type": "string"}}, "required": ["path"]}}, run_script),
]
