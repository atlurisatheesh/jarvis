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
from fastapi.responses import HTMLResponse, JSONResponse, Response, PlainTextResponse

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
mobile_voice_session = AssistantSession()
_WEB_DIR = Path(__file__).parent / "web"
_HTML = (_WEB_DIR / "index.html").read_text(encoding="utf-8")

# Phase 6: opt-in device manager for remote clients.
_device_mgr = None
if config.DEVICE_MANAGER_ENABLED:
    try:
        from .device_manager import get_device_manager
        _device_mgr = get_device_manager()
        print("[web] device_manager enabled — pairing/session/rate-limit active")
    except Exception as _e:
        print(f"[web] device_manager import failed: {_e}")


def _pin_ok(request: Request) -> bool:
    """Require the access PIN on every API call (header or query)."""
    if not config.WEB_PIN:
        return True
    given = request.headers.get("X-Leha-Pin") or request.query_params.get("pin", "")
    return given == config.WEB_PIN


def _device_ok(request: Request) -> tuple[bool, str]:
    """Check device session when device_manager is enabled.

    Returns ``(allowed, reason)``. When the device manager is disabled the
    request is always allowed (existing PIN gate is sufficient).
    """
    if _device_mgr is None:
        return True, ""
    token = (request.headers.get("X-Leha-Device-Token")
             or request.query_params.get("device_token", ""))
    if not token:
        return False, "Missing device session token."
    allowed, reason = _device_mgr.authorize(token, "read")
    return allowed, reason


def _route(text: str, *, explicit: bool = True):
    """Full pipeline: reflexes first, then brain. Same as voice listener.

    Marked 'remote' so shell and destructive tools are refused even if the
    brain calls them. Browser/text messages are explicit by default. Native
    Android microphone traffic can pass explicit=False so background speech
    still has to satisfy the Leha wake/session gate.
    """
    from . import skills as _skills
    _skills.set_origin("remote")
    active_session = session if explicit else mobile_voice_session
    if explicit:
        active_session.activate()
    result = active_session.handle(text, brain.ask)
    if result.ignored_reason and not result.reply:
        if not explicit:
            return text, "", False, result.ignored_reason
        reply = brain.ask(text) or "..."
        set_last_reply(reply)
        return text, reply, True, ""
    return result.heard, (result.reply or "Done, Sir."), result.acted, result.ignored_reason


@app.get("/", response_class=HTMLResponse)
def index():
    return _HTML


@app.get("/manifest.webmanifest")
def manifest():
    return Response((_WEB_DIR / "manifest.webmanifest").read_text(encoding="utf-8"),
                    media_type="application/manifest+json")


@app.get("/sw.js")
def service_worker():
    return Response((_WEB_DIR / "sw.js").read_text(encoding="utf-8"),
                    media_type="application/javascript")


@app.get("/icon.svg")
def icon():
    return Response((_WEB_DIR / "icon.svg").read_text(encoding="utf-8"),
                    media_type="image/svg+xml")


@app.get("/api/health")
def health():
    from . import health as _h
    return JSONResponse(_h.check())


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    """Owner safety dashboard. API calls below still require the PIN."""
    return HTMLResponse((_WEB_DIR / "dashboard.html").read_text(encoding="utf-8"))


@app.get("/api/pro/status")
def pro_status(request: Request):
    if not _pin_ok(request):
        return JSONResponse({"error": "PIN required."}, status_code=401)
    from . import pro_ops
    return JSONResponse(pro_ops.dashboard_status())


@app.post("/api/pro/settings")
async def pro_settings(request: Request):
    if not _pin_ok(request):
        return JSONResponse({"error": "PIN required."}, status_code=401)
    body = await request.json()
    from . import pro_ops
    return JSONResponse(pro_ops.update_owner_settings(body))


@app.get("/api/logs/recent")
def logs_recent(request: Request, limit: int = 80):
    if not _pin_ok(request):
        return JSONResponse({"error": "PIN required."}, status_code=401)
    from . import pro_ops
    return JSONResponse({"lines": pro_ops.recent_logs(limit)})


@app.get("/api/audit/recent")
def audit_recent(request: Request, limit: int = 20):
    if not _pin_ok(request):
        return JSONResponse({"error": "PIN required."}, status_code=401)
    from . import pro_ops
    return JSONResponse(pro_ops.audit_summary(max(1, min(limit, 100))))


@app.post("/api/auth")
async def auth(req: Request):
    body = await req.json()
    ok = (body.get("pin") or "") == config.WEB_PIN
    return JSONResponse({"ok": ok})


# -- Phase 6: device pairing + session endpoints ----------------------------

@app.post("/api/device/pair")
async def device_pair(req: Request):
    """Request pairing for a new device. Owner must approve on laptop."""
    if _device_mgr is None:
        return JSONResponse({"error": "Device manager is not enabled."}, status_code=501)
    if not _pin_ok(req):
        return JSONResponse({"error": "PIN required."}, status_code=401)
    body = await req.json()
    device_id = (body.get("device_id") or "").strip()
    name = (body.get("name") or device_id).strip()
    if not device_id:
        return JSONResponse({"error": "device_id is required."}, status_code=400)
    dev = _device_mgr.request_pairing(device_id, name)
    return JSONResponse({"device_id": dev.device_id, "status": dev.status})


@app.post("/api/device/session")
async def device_session(req: Request):
    """Exchange an approved device_id for a session token."""
    if _device_mgr is None:
        return JSONResponse({"error": "Device manager is not enabled."}, status_code=501)
    if not _pin_ok(req):
        return JSONResponse({"error": "PIN required."}, status_code=401)
    body = await req.json()
    device_id = (body.get("device_id") or "").strip()
    if not device_id:
        return JSONResponse({"error": "device_id is required."}, status_code=400)
    token = _device_mgr.open_session(device_id)
    if token is None:
        return JSONResponse({"error": "Device not approved or unknown."}, status_code=403)
    return JSONResponse({"token": token})


@app.get("/api/device/pending")
async def device_pending(req: Request):
    """List devices awaiting approval (owner only — local or PIN-gated)."""
    if _device_mgr is None:
        return JSONResponse({"error": "Device manager is not enabled."}, status_code=501)
    if not _pin_ok(req):
        return JSONResponse({"error": "PIN required."}, status_code=401)
    pending = _device_mgr.pending()
    return JSONResponse({"pending": [{"device_id": d.device_id, "name": d.name} for d in pending]})


@app.post("/api/device/approve")
async def device_approve(req: Request):
    """Approve a pending device (owner action)."""
    if _device_mgr is None:
        return JSONResponse({"error": "Device manager is not enabled."}, status_code=501)
    if not _pin_ok(req):
        return JSONResponse({"error": "PIN required."}, status_code=401)
    body = await req.json()
    device_id = (body.get("device_id") or "").strip()
    if not device_id:
        return JSONResponse({"error": "device_id is required."}, status_code=400)
    ok = _device_mgr.approve(device_id)
    return JSONResponse({"approved": ok})


@app.post("/api/device/revoke")
async def device_revoke(req: Request):
    """Revoke a device (owner action)."""
    if _device_mgr is None:
        return JSONResponse({"error": "Device manager is not enabled."}, status_code=501)
    if not _pin_ok(req):
        return JSONResponse({"error": "PIN required."}, status_code=401)
    body = await req.json()
    device_id = (body.get("device_id") or "").strip()
    if not device_id:
        return JSONResponse({"error": "device_id is required."}, status_code=400)
    ok = _device_mgr.revoke(device_id)
    return JSONResponse({"revoked": ok})


@app.post("/api/voice")
async def voice(request: Request, audio: UploadFile = File(...)):
    if not _pin_ok(request):
        return JSONResponse({"heard": "", "reply": "Locked. Enter PIN, Sir."}, status_code=401)
    dev_ok, dev_reason = _device_ok(request)
    if not dev_ok:
        return JSONResponse({"heard": "", "reply": dev_reason}, status_code=403)
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
        return JSONResponse({"heard": "", "reply": "", "acted": False, "ignored_reason": "empty"})

    explicit = (request.headers.get("X-Leha-Client") or "").lower() != "android"
    heard, reply, acted, ignored_reason = _route(heard, explicit=explicit)
    return JSONResponse({
        "heard": heard,
        "reply": reply,
        "acted": acted,
        "ignored_reason": ignored_reason,
    })


@app.post("/api/text")
async def text(req: Request):
    if not _pin_ok(req):
        return JSONResponse({"heard": "", "reply": "Locked. Enter PIN, Sir."}, status_code=401)
    dev_ok, dev_reason = _device_ok(req)
    if not dev_ok:
        return JSONResponse({"heard": "", "reply": dev_reason}, status_code=403)
    body = await req.json()
    msg = (body.get("text") or "").strip()
    if not msg:
        return JSONResponse({"heard": "", "reply": "Say something, Sir."})
    heard, reply, acted, ignored_reason = _route(msg, explicit=True)
    return JSONResponse({"heard": heard, "reply": reply, "acted": acted, "ignored_reason": ignored_reason})


def main():
    import socket
    import uvicorn
    # 0.0.0.0 = reachable from your phone on the same Wi-Fi (not just laptop).
    try:
        lan_ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        lan_ip = "<laptop-ip>"
    print(f"[web] {config.ASSISTANT_NAME} on this laptop:  http://127.0.0.1:8001")
    print(f"[web] from your phone (same Wi-Fi):        http://{lan_ip}:8001")
    print(f"[web] ACCESS PIN (enter on phone once):     {config.WEB_PIN}")
    uvicorn.run(app, host="0.0.0.0", port=8001, log_level="warning")


if __name__ == "__main__":
    main()
