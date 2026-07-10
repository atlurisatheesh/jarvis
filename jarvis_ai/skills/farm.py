"""Orchard skills — the unfair advantage.

diagnose_leaf wires to the REAL trained models in D:\\farm-robo (no fake).
It calls farm-robo's own venv + predict_json.py as a subprocess and speaks
the diagnosis + organic-first remedy.
"""
import json
import subprocess
from datetime import datetime
from pathlib import Path

from .. import config


def diagnose_leaf(image_path: str, crop: str = None) -> str:
    img = Path(image_path).expanduser()
    if not img.exists():
        return f"Image not found: {image_path}"
    py = config.FARM_ROBO_PYTHON
    script = Path(config.FARM_ROBO_DIR) / "predict_json.py"
    if not Path(py).exists() or not script.exists():
        return "farm-robo not wired. Check FARM_ROBO_PYTHON and FARM_ROBO_DIR in config."

    cmd = [py, "predict_json.py", str(img)]
    if crop:
        cmd += ["--crop", crop]
    try:
        r = subprocess.run(cmd, cwd=config.FARM_ROBO_DIR,
                           capture_output=True, text=True, timeout=120)
        line = (r.stdout or "").strip().splitlines()
        data = json.loads(line[-1]) if line else {}
    except Exception as e:
        return f"Diagnosis failed: {e}"

    if not data.get("ok"):
        return f"Diagnosis error: {data.get('error', 'unknown')}"
    if data.get("uncertain"):
        return data.get("message", "Couldn't tell the crop. Take a clearer close-up.")

    crop_name = data.get("crop", "crop")
    disease = data.get("disease", "?")
    conf = int(data.get("confidence", 0) * 100)
    if data.get("is_healthy"):
        return f"{crop_name.title()} looks healthy ({conf}% sure). No treatment needed."

    parts = [f"{crop_name.title()}: {disease} at {conf}% confidence."]
    tr = data.get("treatment", {})
    if tr.get("organic"):
        parts.append("Organic first: " + "; ".join(tr["organic"][:2]) + ".")
    if tr.get("chemical"):
        parts.append("If severe: " + tr["chemical"][0] + ".")
    if tr.get("prevention"):
        parts.append("Prevent: " + tr["prevention"][0] + ".")
    return " ".join(parts)


def get_weather() -> str:
    import requests
    try:
        url = ("https://api.open-meteo.com/v1/forecast"
               f"?latitude={config.FARM_LAT}&longitude={config.FARM_LON}"
               "&current=temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m"
               "&daily=precipitation_sum&forecast_days=2&timezone=auto")
        d = requests.get(url, timeout=15).json()
        c = d["current"]
        rain = d["daily"]["precipitation_sum"]
        return (f"Now {c['temperature_2m']}C, humidity {c['relative_humidity_2m']}%, "
                f"wind {c['wind_speed_10m']} km/h. Rain today {rain[0]}mm, tomorrow {rain[1]}mm.")
    except Exception as e:
        return f"Weather unavailable: {e}"


def current_location() -> str:
    """Approximate current location from the internet connection (city-level)."""
    import requests
    try:
        d = requests.get("https://ipapi.co/json/", timeout=8).json()
        if d.get("city"):
            return (f"You are near {d['city']}, {d.get('region', '')}, "
                    f"{d.get('country_name', '')}, based on the internet connection.")
    except Exception:
        pass
    try:
        d = requests.get("http://ip-api.com/json/", timeout=8).json()
        if d.get("status") == "success":
            return (f"You are near {d['city']}, {d.get('regionName', '')}, "
                    f"{d.get('country', '')}, based on the internet connection.")
    except Exception as e:
        return f"Location unavailable right now: {e}"
    return "Location unavailable right now, Sir."


# Cities the geocoder only knows by their official/renamed spelling.
_CITY_ALIASES = {
    "bangalore": "Bengaluru",
    "bombay": "Mumbai",
    "madras": "Chennai",
    "calcutta": "Kolkata",
    "pondicherry": "Puducherry",
    "trivandrum": "Thiruvananthapuram",
    "vizag": "Visakhapatnam",
    "mysore": "Mysuru",
    "mangalore": "Mangaluru",
    "belgaum": "Belagavi",
    "gurgaon": "Gurugram",
}


def _geocode_once(name: str):
    import requests
    d = requests.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": name, "count": 10, "language": "en"},
        timeout=8,
    ).json()
    return d.get("results") or []


def _geocode(place: str):
    """Free geocoding via open-meteo (no API key). Returns (lat, lon, label).

    Prefers India and highest population; applies common Indian-city aliases
    (Bangalore->Bengaluru) so old names resolve to the right metro instead of a
    tiny same-named village elsewhere.
    """
    place = (place or "").strip()
    query = _CITY_ALIASES.get(place.lower(), place)
    results = _geocode_once(query)
    india = [r for r in results if r.get("country_code") == "IN"]
    # No Indian match? Retry biased to India before trusting a foreign result.
    if not india:
        india = [r for r in _geocode_once(f"{query} India") if r.get("country_code") == "IN"]
    pool = india or results
    if not pool:
        return None
    r = max(pool, key=lambda x: x.get("population") or 0)
    label = ", ".join(x for x in (r.get("name"), r.get("admin1"), r.get("country")) if x)
    return float(r["latitude"]), float(r["longitude"]), label


def _my_coords():
    """Approximate current lat/lon from the internet connection."""
    import requests
    for url, la, lo in (
        ("https://ipapi.co/json/", "latitude", "longitude"),
        ("http://ip-api.com/json/", "lat", "lon"),
    ):
        try:
            d = requests.get(url, timeout=8).json()
            if d.get(la) is not None and d.get(lo) is not None:
                return float(d[la]), float(d[lo])
        except Exception:
            continue
    return None


def travel_distance(destination: str) -> str:
    """Approximate distance from the user's current location to a destination."""
    import math
    dest = _geocode((destination or "").strip())
    if not dest:
        return f"I could not find {destination} on the map, Sir."
    here = _my_coords()
    if not here:
        return "I could not determine your current location right now, Sir."
    lat1, lon1 = here
    lat2, lon2, label = dest
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    straight = r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    road = straight * 1.3  # roads are typically ~30% longer than straight line
    return (f"{label} is about {straight:.0f} kilometres away in a straight line, "
            f"roughly {road:.0f} kilometres by road, Sir.")


def farm_journal(entry: str) -> str:
    f = config.MEMORY_DIR / "farm_journal.txt"
    config.MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    with f.open("a", encoding="utf-8") as fh:
        fh.write(f"{datetime.now():%Y-%m-%d %H:%M} | {entry}\n")
    return "Logged to the farm journal."


SKILLS = [
    ({"name": "diagnose_leaf",
      "description": "Diagnose crop disease from a leaf photo using the real trained farm models. Optional crop hint.",
      "parameters": {"type": "object",
                     "properties": {"image_path": {"type": "string"},
                                    "crop": {"type": "string"}},
                     "required": ["image_path"]}}, diagnose_leaf),
    ({"name": "get_weather", "description": "Get current weather and rain forecast for the farm location.",
      "parameters": {"type": "object", "properties": {}}}, get_weather),
    ({"name": "current_location",
      "description": "Get the user's approximate current location (city/region) from the internet connection.",
      "parameters": {"type": "object", "properties": {}}}, current_location),
    ({"name": "travel_distance",
      "description": "Approximate distance from the user's current location to a place, e.g. 'how far is Tirupati'.",
      "parameters": {"type": "object",
                     "properties": {"destination": {"type": "string"}},
                     "required": ["destination"]}}, travel_distance),
    ({"name": "farm_journal", "description": "Log a hands-free note to the farm journal.",
      "parameters": {"type": "object",
                     "properties": {"entry": {"type": "string"}}, "required": ["entry"]}}, farm_journal),
]
