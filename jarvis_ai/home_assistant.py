"""Phase 7: Home Assistant integration (scoped token).

Uses Home Assistant as the smart-home hub instead of writing per-brand code for
every bulb/AC/TV/sensor. Exposes only named entities and scenes through a scoped
long-lived access token.

Safety / graceful degrade:

* When ``config.HOME_ASSISTANT_ENABLED`` is False (no URL or no token), every
  call returns a clear "not configured" message and **nothing is contacted**.
* All network calls are wrapped; a server/network error returns a readable
  string rather than raising into the voice loop.
* ``requests`` is imported lazily so the module imports with zero extra deps.

This module is additive: it is not auto-registered into the live skill set, so
no existing behavior changes until the owner configures a token and wires it in.
"""
from __future__ import annotations

from . import config

_NOT_CONFIGURED = (
    "Home Assistant is not configured, Sir. Set HOME_ASSISTANT_URL and put a "
    "long-lived token in .home_assistant_token to enable smart-home control."
)


def is_configured() -> bool:
    return bool(config.HOME_ASSISTANT_ENABLED)


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {config.HOME_ASSISTANT_TOKEN}",
        "Content-Type": "application/json",
    }


def _base() -> str:
    return config.HOME_ASSISTANT_URL.rstrip("/")


def _get(path: str):
    import requests
    return requests.get(f"{_base()}{path}", headers=_headers(), timeout=8)


def _post(path: str, payload: dict):
    import requests
    return requests.post(f"{_base()}{path}", headers=_headers(), json=payload, timeout=8)


def ping() -> str:
    """Confirm the HA API is reachable with the configured token."""
    if not is_configured():
        return _NOT_CONFIGURED
    try:
        r = _get("/api/")
        if r.status_code == 200:
            return "Home Assistant connected, Sir."
        return f"Home Assistant returned status {r.status_code}."
    except Exception as e:  # network/timeout/import
        return f"Home Assistant unreachable: {e}"


def list_entities(domain: str = "") -> str:
    """List entity ids, optionally filtered by domain (light, switch, scene...)."""
    if not is_configured():
        return _NOT_CONFIGURED
    try:
        r = _get("/api/states")
        if r.status_code != 200:
            return f"Home Assistant returned status {r.status_code}."
        states = r.json()
        ids = [s.get("entity_id", "") for s in states]
        if domain:
            ids = [e for e in ids if e.startswith(f"{domain}.")]
        if not ids:
            return f"No {domain or 'entities'} found, Sir."
        return "Entities: " + ", ".join(ids[:40])
    except Exception as e:
        return f"Home Assistant error: {e}"


def call_service(domain: str, service: str, entity_id: str) -> str:
    """Call a service, e.g. light.turn_on on light.living_room."""
    if not is_configured():
        return _NOT_CONFIGURED
    try:
        r = _post(f"/api/services/{domain}/{service}", {"entity_id": entity_id})
        if r.status_code in (200, 201):
            return f"Done: {service} on {entity_id}, Sir."
        return f"Home Assistant returned status {r.status_code}."
    except Exception as e:
        return f"Home Assistant error: {e}"


def turn_on(entity_id: str) -> str:
    domain = entity_id.split(".", 1)[0] if "." in entity_id else "homeassistant"
    return call_service(domain, "turn_on", entity_id)


def turn_off(entity_id: str) -> str:
    domain = entity_id.split(".", 1)[0] if "." in entity_id else "homeassistant"
    return call_service(domain, "turn_off", entity_id)


def activate_scene(scene_id: str) -> str:
    if not scene_id.startswith("scene."):
        scene_id = f"scene.{scene_id}"
    return call_service("scene", "turn_on", scene_id)


SKILLS = [
    ({"name": "home_assistant_ping",
      "description": "Check whether Home Assistant smart-home control is connected.",
      "parameters": {"type": "object", "properties": {}}}, ping),
    ({"name": "home_assistant_list",
      "description": "List Home Assistant entities, optionally by domain (light, switch, scene).",
      "parameters": {"type": "object",
                     "properties": {"domain": {"type": "string"}}}}, list_entities),
    ({"name": "home_assistant_turn_on",
      "description": "Turn on a Home Assistant entity by entity_id (e.g. light.living_room).",
      "parameters": {"type": "object",
                     "properties": {"entity_id": {"type": "string"}},
                     "required": ["entity_id"]}}, turn_on),
    ({"name": "home_assistant_turn_off",
      "description": "Turn off a Home Assistant entity by entity_id.",
      "parameters": {"type": "object",
                     "properties": {"entity_id": {"type": "string"}},
                     "required": ["entity_id"]}}, turn_off),
    ({"name": "home_assistant_scene",
      "description": "Activate a Home Assistant scene by name or scene.* id.",
      "parameters": {"type": "object",
                     "properties": {"scene_id": {"type": "string"}},
                     "required": ["scene_id"]}}, activate_scene),
]
