"""One-time setup: create the owner's ElevenLabs voice clone for Leha.

1. Uploads the owner's cleaned voice recording as an Instant Voice Clone
   named "Leha Owner" (reuses it if it already exists).
2. Saves the resulting voice id to D:\\jarvis\\.elevenlabs_voice so config
   picks it up and mouth.py speaks with it.
3. Generates a short test line to verify the clone works.

Usage (from D:\\jarvis):
    python tools/setup_elevenlabs_voice.py
"""
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jarvis_ai import config  # noqa: E402

API = "https://api.elevenlabs.io/v1"
VOICE_NAME = "Leha Owner"
SAMPLES = [
    ROOT / "WhatsApp%20Video%202026-02-20%20at%208.26.37%20PM_audio_cleaned.mp3",
    ROOT / "WhatsApp%20Video%202026-02-13%20at%208.59.02%20PM_audio_cleaned.mp3",
]


def headers():
    return {"xi-api-key": config.ELEVENLABS_API_KEY}


def find_existing_voice() -> str | None:
    r = requests.get(f"{API}/voices", headers=headers(), timeout=15)
    r.raise_for_status()
    for v in r.json().get("voices", []):
        if v.get("name") == VOICE_NAME:
            return v["voice_id"]
    return None


def create_voice() -> str:
    files = []
    for s in SAMPLES:
        if s.exists():
            files.append(("files", (s.name, open(s, "rb"), "audio/mpeg")))
    if not files:
        raise SystemExit(f"No voice sample files found in {ROOT}")
    r = requests.post(
        f"{API}/voices/add",
        headers=headers(),
        data={"name": VOICE_NAME,
              "description": "Owner voice for the Leha assistant (private use)."},
        files=files,
        timeout=120,
    )
    if not r.ok:
        raise SystemExit(f"Voice creation failed: HTTP {r.status_code}: {r.text[:300]}")
    return r.json()["voice_id"]


def main() -> int:
    if not config.ELEVENLABS_API_KEY:
        raise SystemExit("No API key found in .elevenlabs_key")
    voice_id = find_existing_voice()
    if voice_id:
        print(f"[elevenlabs] reusing existing voice '{VOICE_NAME}': {voice_id}")
    else:
        print("[elevenlabs] creating instant voice clone from owner recordings...")
        voice_id = create_voice()
        print(f"[elevenlabs] created voice: {voice_id}")

    (ROOT / ".elevenlabs_voice").write_text(voice_id, encoding="utf-8")
    print(f"[elevenlabs] saved voice id to .elevenlabs_voice")

    # Smoke test: synthesize a short line and confirm we get audio bytes.
    r = requests.post(
        f"{API}/text-to-speech/{voice_id}?output_format=mp3_22050_32",
        headers={**headers(), "Content-Type": "application/json"},
        json={"text": "Hello Sir, this is Leha speaking with the new voice.",
              "model_id": config.ELEVENLABS_MODEL},
        timeout=30,
    )
    if not r.ok:
        raise SystemExit(f"TTS smoke test failed: HTTP {r.status_code}: {r.text[:300]}")
    out = ROOT / "jarvis_ai" / "voices" / "elevenlabs_test.mp3"
    out.write_bytes(r.content)
    print(f"[elevenlabs] smoke test OK — {len(r.content)} bytes -> {out}")
    print("[elevenlabs] DONE. Restart Leha to speak with the cloned voice.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
