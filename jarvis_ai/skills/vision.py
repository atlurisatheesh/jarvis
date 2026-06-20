"""Screen vision: real understanding of what's on screen via Groq vision model.

Goes beyond OCR (desktop.read_screen) — describes UI, images, layout, charts,
answers free-form questions about the screen like Siri AI 2026 screen awareness.
"""
import base64
import tempfile
import os

import requests

from .. import config

# Groq vision-capable model. llama-4 scout supports image input.
_GROQ_VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
_GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"


def _screenshot_b64() -> str:
    import pyautogui
    img = pyautogui.screenshot()
    with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as f:
        path = f.name
    try:
        # downscale to keep tokens/latency low (vision models cap ~1568px)
        w, h = img.size
        if w > 1280:
            img = img.resize((1280, int(h * 1280 / w)))
        img.save(path, "PNG")
        with open(path, "rb") as fh:
            return base64.b64encode(fh.read()).decode("ascii")
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def see_screen(question: str = "What is on the screen?") -> str:
    """Look at the screen and answer a question about it (vision, not just OCR)."""
    if not config.GROQ_API_KEY:
        return "Vision needs GROQ_API_KEY, Sir."
    try:
        b64 = _screenshot_b64()
    except Exception as e:
        return f"Screenshot failed: {e}"

    payload = {
        "model": _GROQ_VISION_MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text",
                 "text": f"{question}\nAnswer in one short spoken sentence, max 20 words."},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ],
        }],
        "max_tokens": 120,
        "temperature": 0.2,
    }
    try:
        r = requests.post(
            _GROQ_CHAT_URL,
            headers={"Authorization": f"Bearer {config.GROQ_API_KEY}",
                     "Content-Type": "application/json"},
            json=payload,
            timeout=config.GROQ_TIMEOUT_SECONDS,
        )
        if not r.ok:
            return f"Vision error {r.status_code}: {r.text[:120]}"
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"Vision unavailable: {e}"


SKILLS = [
    ({"name": "see_screen",
      "description": "Look at the screen with computer vision and answer a question about "
                     "what is visible (UI, images, charts, layout) — richer than plain OCR.",
      "parameters": {"type": "object", "properties": {
          "question": {"type": "string", "description": "What to find/describe on screen"}
      }}}, see_screen),
]
