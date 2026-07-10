"""Create and test a replacement ElevenLabs clone without risking the live voice.

By default this creates a candidate and writes a private test MP3. The current
Leha voice is left untouched. Pass --activate only after listening to the test.

Usage:
    python tools/redo_elevenlabs_voice.py "C:\\path\\to\\voice.mp3"
    python tools/redo_elevenlabs_voice.py "C:\\path\\to\\voice.mp3" --activate
"""
import argparse
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
import shutil
import sys

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jarvis_ai import config  # noqa: E402

API = "https://api.elevenlabs.io/v1"
DEFAULT_SAMPLE = ROOT / "WhatsApp%20Video%202026-02-20%20at%208.26.37%20PM_audio_cleaned.mp3"
LIVE_VOICE_FILE = ROOT / ".elevenlabs_voice"
CANDIDATE_FILE = ROOT / ".elevenlabs_candidate_voice"
BACKUP_FILE = ROOT / ".elevenlabs_voice.backup"


def headers():
    return {"xi-api-key": config.ELEVENLABS_API_KEY}


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("samples", nargs="*", type=Path, default=[DEFAULT_SAMPLE])
    parser.add_argument(
        "--activate",
        action="store_true",
        help="Back up the current voice id and activate the tested candidate.",
    )
    return parser.parse_args()


def create_candidate(samples: list[Path]) -> str:
    missing = [str(path) for path in samples if not path.exists()]
    if missing:
        raise SystemExit("Missing sample(s): " + ", ".join(missing))

    with ExitStack() as stack:
        files = []
        for sample in samples:
            handle = stack.enter_context(sample.open("rb"))
            mime = "audio/mpeg" if sample.suffix.lower() in {".mp3", ".m4a"} else "audio/wav"
            files.append(("files", (sample.name, handle, mime)))
        response = requests.post(
            f"{API}/voices/add",
            headers=headers(),
            data={
                "name": f"Leha Candidate {datetime.now():%Y%m%d-%H%M%S}",
                "description": "Private Leha candidate; live clone is preserved.",
                "remove_background_noise": "true",
            },
            files=files,
            timeout=120,
        )
    if not response.ok:
        raise SystemExit(f"Voice creation failed: HTTP {response.status_code}")
    voice_id = response.json().get("voice_id", "")
    if not voice_id:
        raise SystemExit("Voice creation returned no voice id")
    return voice_id


def render_test(voice_id: str) -> Path:
    response = requests.post(
        f"{API}/text-to-speech/{voice_id}?output_format=mp3_44100_64",
        headers={**headers(), "Content-Type": "application/json"},
        json={
            "text": "Hello Sir, this is Leha. Tell me what you need.",
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {
                "stability": config.ELEVENLABS_STABILITY,
                "similarity_boost": config.ELEVENLABS_SIMILARITY_BOOST,
                "style": config.ELEVENLABS_STYLE,
                "use_speaker_boost": config.ELEVENLABS_SPEAKER_BOOST,
            },
        },
        timeout=60,
    )
    if not response.ok:
        raise SystemExit(f"TTS test failed: HTTP {response.status_code}")
    output = ROOT / "jarvis_ai" / "voices" / "elevenlabs_candidate_test.mp3"
    output.write_bytes(response.content)
    return output


def main() -> int:
    args = parse_args()
    if not config.ELEVENLABS_API_KEY:
        raise SystemExit("No ElevenLabs API key is configured")

    voice_id = create_candidate(args.samples)
    CANDIDATE_FILE.write_text(voice_id, encoding="utf-8")
    output = render_test(voice_id)
    print(f"[elevenlabs] candidate test ready: {output}")
    print("[elevenlabs] the current live voice has not been changed or deleted")

    if args.activate:
        if LIVE_VOICE_FILE.exists():
            shutil.copyfile(LIVE_VOICE_FILE, BACKUP_FILE)
        shutil.copyfile(CANDIDATE_FILE, LIVE_VOICE_FILE)
        print("[elevenlabs] candidate activated; previous live id backed up")
        print("[elevenlabs] restart Leha to load it")
    else:
        print("[elevenlabs] listen first, then rerun with --activate only if it is better")
    return 0


if __name__ == "__main__":
    sys.exit(main())
