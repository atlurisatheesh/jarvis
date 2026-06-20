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
    ({"name": "farm_journal", "description": "Log a hands-free note to the farm journal.",
      "parameters": {"type": "object",
                     "properties": {"entry": {"type": "string"}}, "required": ["entry"]}}, farm_journal),
]
