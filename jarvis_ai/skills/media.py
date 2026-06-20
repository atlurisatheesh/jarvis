"""Media playback skills via Windows media keys and YouTube playback."""
import re
import urllib.parse
import webbrowser

import requests

from .system import _tap, VK


def media_play_pause() -> str:
    _tap(VK["media_play_pause"])
    return "Toggled playback."


def media_next() -> str:
    _tap(VK["media_next"])
    return "Next track."


def media_prev() -> str:
    _tap(VK["media_prev"])
    return "Previous track."


def _youtube_search_first_watch(query: str) -> str | None:
    url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(query)
    try:
        html = requests.get(
            url,
            timeout=12,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0 Safari/537.36"
                )
            },
        ).text
    except Exception:
        return None

    seen = set()
    for video_id in re.findall(r'"videoId":"([A-Za-z0-9_-]{11})"', html):
        if video_id in seen:
            continue
        seen.add(video_id)
        return "https://www.youtube.com/watch?v=" + video_id
    return None


def play_youtube(query: str) -> str:
    """Search YouTube and open the first playable video result."""
    query = (query or "").strip()
    if not query:
        webbrowser.open("https://www.youtube.com")
        return "Opening YouTube."

    watch_url = _youtube_search_first_watch(query)
    if not watch_url:
        search_url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(query)
        webbrowser.open(search_url)
        return f"I could not pick a video, so I searched YouTube for {query}."

    webbrowser.open(watch_url)
    return f"Playing {query} on YouTube."


SKILLS = [
    ({"name": "media_play_pause", "description": "Play or pause current media.",
      "parameters": {"type": "object", "properties": {}}}, media_play_pause),
    ({"name": "media_next", "description": "Skip to the next track.",
      "parameters": {"type": "object", "properties": {}}}, media_next),
    ({"name": "media_prev", "description": "Go to the previous track.",
      "parameters": {"type": "object", "properties": {}}}, media_prev),
    ({"name": "play_youtube",
      "description": "Play a requested song, music, artist, movie clip, or video on YouTube by opening the first watch result. Use this for commands like 'play Ilayaraja Telugu songs', 'play music on YouTube', or 'play this in YouTube'.",
      "parameters": {"type": "object",
                     "properties": {"query": {"type": "string", "description": "What to play on YouTube"}},
                     "required": ["query"]}}, play_youtube),
]
