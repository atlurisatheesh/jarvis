"""Phase 6: secure device manager for remote clients.

Turns the laptop into the pairing authority for Android/PWA/Telegram clients.
Responsibilities:

* **Pairing approval** — a new device is ``pending`` until the owner approves it
  on the laptop. Unknown/pending devices get no session.
* **Session tokens with expiry** — an approved device exchanges its device id
  for a short-lived opaque session token (``DEVICE_SESSION_TTL_SECONDS``).
* **Per-device rate limiting** — a sliding 60-second window caps requests at
  ``DEVICE_RATE_LIMIT_PER_MINUTE`` per device.
* **Per-device capability scoping** — each device carries an allow-set of
  capability tags (e.g. ``{"read", "media"}``); destructive tags are never
  granted by default.

This module is pure logic with a small JSON persistence file. It is **not**
wired into the live web server unless ``config.DEVICE_MANAGER_ENABLED`` is True,
so the current PIN-gated path is untouched until the owner opts in.
"""
from __future__ import annotations

import json
import secrets
import threading
import time
from dataclasses import dataclass, field, asdict
from typing import Iterable

from . import config

_STORE = config.MEMORY_DIR / "devices.json"

# Capability tags. Remote devices may never be granted destructive control.
SAFE_CAPABILITIES = frozenset({"read", "media", "query"})
ALL_CAPABILITIES = frozenset(SAFE_CAPABILITIES | {"control", "destructive"})


@dataclass
class Device:
    device_id: str
    name: str
    status: str = "pending"          # pending | approved | revoked
    capabilities: set = field(default_factory=lambda: set(SAFE_CAPABILITIES))
    paired_at: float = 0.0

    def to_json(self) -> dict:
        d = asdict(self)
        d["capabilities"] = sorted(self.capabilities)
        return d

    @classmethod
    def from_json(cls, d: dict) -> "Device":
        return cls(
            device_id=d["device_id"],
            name=d.get("name", d["device_id"]),
            status=d.get("status", "pending"),
            capabilities=set(d.get("capabilities", SAFE_CAPABILITIES)),
            paired_at=float(d.get("paired_at", 0.0)),
        )


@dataclass
class _Session:
    device_id: str
    token: str
    expires_at: float


class DeviceManager:
    """Thread-safe pairing + session + rate-limit + capability authority."""

    def __init__(self, session_ttl: int | None = None, rate_limit: int | None = None):
        self._lock = threading.RLock()
        self._devices: dict[str, Device] = {}
        self._sessions: dict[str, _Session] = {}        # token -> session
        self._hits: dict[str, list[float]] = {}         # device_id -> timestamps
        self._ttl = int(session_ttl if session_ttl is not None else config.DEVICE_SESSION_TTL_SECONDS)
        self._rate = int(rate_limit if rate_limit is not None else config.DEVICE_RATE_LIMIT_PER_MINUTE)
        self._load()

    # -- persistence -------------------------------------------------------
    def _load(self) -> None:
        if not _STORE.exists():
            return
        try:
            data = json.loads(_STORE.read_text(encoding="utf-8"))
        except Exception:
            return
        for d in data.get("devices", []):
            dev = Device.from_json(d)
            self._devices[dev.device_id] = dev

    def _save(self) -> None:
        config.MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        payload = {"devices": [d.to_json() for d in self._devices.values()]}
        _STORE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # -- pairing -----------------------------------------------------------
    def request_pairing(self, device_id: str, name: str = "") -> Device:
        """Register a device as ``pending``. Idempotent for an existing id."""
        with self._lock:
            dev = self._devices.get(device_id)
            if dev is None:
                dev = Device(device_id=device_id, name=name or device_id)
                self._devices[device_id] = dev
                self._save()
            return dev

    def approve(self, device_id: str, capabilities: Iterable[str] | None = None) -> bool:
        """Owner approves a device. Destructive caps are stripped for safety."""
        with self._lock:
            dev = self._devices.get(device_id)
            if dev is None:
                return False
            if capabilities is not None:
                dev.capabilities = {c for c in capabilities if c in SAFE_CAPABILITIES}
            dev.status = "approved"
            dev.paired_at = time.time()
            self._save()
            return True

    def revoke(self, device_id: str) -> bool:
        with self._lock:
            dev = self._devices.get(device_id)
            if dev is None:
                return False
            dev.status = "revoked"
            # Drop any live sessions for this device.
            self._sessions = {t: s for t, s in self._sessions.items() if s.device_id != device_id}
            self._save()
            return True

    def list_devices(self) -> list[Device]:
        with self._lock:
            return list(self._devices.values())

    def pending(self) -> list[Device]:
        with self._lock:
            return [d for d in self._devices.values() if d.status == "pending"]

    # -- sessions ----------------------------------------------------------
    def open_session(self, device_id: str) -> str | None:
        """Exchange an approved device id for a short-lived session token."""
        with self._lock:
            dev = self._devices.get(device_id)
            if dev is None or dev.status != "approved":
                return None
            token = secrets.token_urlsafe(24)
            self._sessions[token] = _Session(device_id, token, time.time() + self._ttl)
            return token

    def session_device(self, token: str) -> str | None:
        """Return the device id for a live (non-expired) token, else None."""
        with self._lock:
            s = self._sessions.get(token)
            if s is None:
                return None
            if time.time() >= s.expires_at:
                del self._sessions[token]
                return None
            return s.device_id

    def close_session(self, token: str) -> None:
        with self._lock:
            self._sessions.pop(token, None)

    # -- rate limiting -----------------------------------------------------
    def allow_request(self, device_id: str) -> bool:
        """Sliding 60-second window; True if under the per-device cap."""
        now = time.time()
        with self._lock:
            hits = [t for t in self._hits.get(device_id, []) if now - t < 60.0]
            if len(hits) >= self._rate:
                self._hits[device_id] = hits
                return False
            hits.append(now)
            self._hits[device_id] = hits
            return True

    # -- capability gate ---------------------------------------------------
    def has_capability(self, device_id: str, capability: str) -> bool:
        with self._lock:
            dev = self._devices.get(device_id)
            if dev is None or dev.status != "approved":
                return False
            return capability in dev.capabilities

    def authorize(self, token: str, capability: str = "read") -> tuple[bool, str]:
        """Full gate for a remote request: valid session + rate + capability.

        Returns ``(allowed, reason)``. ``reason`` is empty when allowed.
        """
        device_id = self.session_device(token)
        if device_id is None:
            return False, "invalid or expired session"
        if not self.allow_request(device_id):
            return False, "rate limit exceeded"
        if not self.has_capability(device_id, capability):
            return False, f"device lacks '{capability}' capability"
        return True, ""


_MANAGER: DeviceManager | None = None
_MGR_LOCK = threading.Lock()


def get_device_manager() -> DeviceManager:
    """Process-wide singleton (mirrors get_background_jobs / get_manager)."""
    global _MANAGER
    with _MGR_LOCK:
        if _MANAGER is None:
            _MANAGER = DeviceManager()
        return _MANAGER
