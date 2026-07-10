"""Pre-render Leha's short fixed phrases in the owner's cloned voice.

Chatterbox clone synthesis takes ~1 minute per phrase on this CPU-only laptop,
far too slow for live replies. Instead, this one-time script renders the short
fixed phrases Leha speaks often (wake acks, greetings, routine lines) into
voices/clone_cache/. At runtime, mouth.py plays a cached phrase instantly in
the owner's voice and uses the fast Edge neural voice for everything else.

Usage (from D:\\jarvis, inside the venv):
    python tools/prerender_clone_phrases.py            # render default phrases
    python tools/prerender_clone_phrases.py --list     # show phrases + status
    python tools/prerender_clone_phrases.py --phrase "Yes, Sir?"   # add one

Re-running skips phrases already rendered.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jarvis_ai import config  # noqa: E402
from jarvis_ai.mouth import clone_cache_key  # noqa: E402


def default_phrases() -> list[str]:
    phrases = [
        "Yes, Sir?",
        "Ready.",
        f"{config.ASSISTANT_NAME} online.",
        "Done, Sir.",
        "On it, Sir.",
        "One moment, Sir.",
        "I heard you, Sir.",
        "Good morning, Sir.",
        "Good night, Sir.",
        "Welcome back, Sir.",
    ]
    for steps in config.ROUTINES.values():
        for step in steps:
            if step.get("action") == "say" and step.get("text"):
                phrases.append(step["text"])
    seen = set()
    unique = []
    for p in phrases:
        key = clone_cache_key(p)
        if key and key not in seen:
            seen.add(key)
            unique.append(p)
    return unique


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phrase", action="append", default=[],
                        help="extra phrase to render (repeatable)")
    parser.add_argument("--list", action="store_true", help="list phrases and cache status")
    args = parser.parse_args()

    cache_dir = Path(config.CLONE_PHRASE_CACHE_DIR)
    cache_dir.mkdir(parents=True, exist_ok=True)
    phrases = default_phrases() + args.phrase

    if args.list:
        for p in phrases:
            path = cache_dir / f"{clone_cache_key(p)}.wav"
            print(f"{'CACHED ' if path.exists() else 'missing'}  {p}")
        return 0

    from jarvis_ai import voice_clone

    reference = voice_clone.reference_audio()
    print(f"[prerender] reference voice: {reference}")
    pending = [p for p in phrases if not (cache_dir / f"{clone_cache_key(p)}.wav").exists()]
    if not pending:
        print("[prerender] all phrases already cached.")
        return 0
    print(f"[prerender] rendering {len(pending)} phrases (~1 min each on CPU)...")
    failures = 0
    for i, phrase in enumerate(pending, 1):
        out = cache_dir / f"{clone_cache_key(phrase)}.wav"
        print(f"[prerender] ({i}/{len(pending)}) {phrase!r}")
        try:
            voice_clone.synthesize(phrase, str(out), reference)
        except Exception as e:
            failures += 1
            print(f"[prerender]   FAILED: {e}")
    done = len(pending) - failures
    print(f"[prerender] finished: {done} rendered, {failures} failed, cache: {cache_dir}")
    return 1 if failures and not done else 0


if __name__ == "__main__":
    sys.exit(main())
