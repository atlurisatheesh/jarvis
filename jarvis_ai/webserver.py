"""Browser-mic front end for JARVIS.

The browser captures the mic (clean, bypasses PortAudio issues) and POSTs
audio to this LOCAL server. Transcription, brain, and tools all run locally
or via Groq cloud. Reply is shown on screen and spoken by the browser.

    python -m jarvis_ai.webserver
    open http://127.0.0.1:8001 in Chrome
"""
import os
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse

from . import config
from .assistant_session import AssistantSession
from .brain import Brain
from .ears import Ears
from .assistant_core import set_last_reply

app = FastAPI(title=config.ASSISTANT_NAME)
print("[web] loading STT + brain ...")
ears = Ears()
brain = Brain()
session = AssistantSession()
_HTML = (Path(__file__).parent / "web" / "index.html").read_text(encoding="utf-8")


@app.get("/", response_class=HTMLResponse)
def index():
    return _HTML


@app.post("/api/voice")
async def voice(audio: UploadFile = File(...)):
    data = await audio.read()
    with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as f:
        f.write(data)
        path = f.name
    try:
        heard = ears.transcribe_file(path).strip()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass

    if not heard:
        return JSONResponse({"heard": "", "reply": "", "acted": False})

    result = session.handle(heard, brain.ask)
    return JSONResponse({
        "heard": result.heard,
        "reply": result.reply,
        "acted": result.acted,
        "ignored_reason": result.ignored_reason,
    })


@app.post("/api/text")
async def text(req: Request):
    body = await req.json()
    msg = (body.get("text") or "").strip()
    if not msg:
        return JSONResponse({"heard": "", "reply": "Say something, Sir."})
    reply = brain.ask(msg)
    set_last_reply(reply)
    return JSONResponse({"heard": msg, "reply": reply})


def main():
    import uvicorn
    print(f"[web] {config.ASSISTANT_NAME} at http://127.0.0.1:8001")
    uvicorn.run(app, host="127.0.0.1", port=8001, log_level="warning")


if __name__ == "__main__":
    main()
