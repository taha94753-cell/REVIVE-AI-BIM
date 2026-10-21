"""
Live site weather from Open-Meteo (https://open-meteo.com): free for non-commercial
use, no API key, data under CC BY 4.0. One request returns the past 14 days of
observed weather and a 16-day forecast for the site coordinates.

Each day is classed as a likely lost working day for weather-sensitive work when it
breaks a rule in config.yaml (weather.lost_day_rules): heavy rain, high wind,
extreme heat for concreting, or frost risk.

How it is used
  * Past days -> the phone page suggests "weather days lost since the last update"
    (the site engineer confirms or edits it), which feeds the model's weather input.
  * Forecast days -> optional: lost days ahead are added to weather-sensitive
    activities on site on those days before the recovery plan is optimised.
If the internet is not available the app keeps working and asks for manual entry.
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from .config import load_config

URL = "https://api.open-meteo.com/v1/forecast"
DAILY = ["precipitation_sum", "temperature_2m_max", "temperature_2m_min", "wind_speed_10m_max"]
PLACES = {
    "Islamabad": (33.69, 73.06), "Rawalpindi": (33.60, 73.04), "Lahore": (31.55, 74.34),
    "Karachi": (24.86, 67.01), "Peshawar": (34.01, 71.58), "Quetta": (30.18, 66.98),
    "Multan": (30.20, 71.47), "Faisalabad": (31.42, 73.08), "Hyderabad": (25.40, 68.37),
    "Sialkot": (32.49, 74.53), "Gilgit": (35.92, 74.31), "Muzaffarabad": (34.37, 73.47),
}
PROVINCE_DEFAULT = {"Punjab": "Lahore", "Sindh": "Karachi", "Khyber Pakhtunkhwa": "Peshawar",
                    "Balochistan": "Quetta", "Islamabad Capital Territory": "Islamabad",
                    "Gilgit-Baltistan": "Gilgit", "Azad Jammu & Kashmir": "Muzaffarabad"}
_CACHE: dict = {}
_CACHE_MAX = 256          # bounded: the cache is keyed by coordinates a user can choose


def place(name: str | None = None, province: str | None = None) -> dict:
    name = name if name in PLACES else PROVINCE_DEFAULT.get(province or "", "Islamabad")
    lat, lon = PLACES[name]
    return {"name": name, "lat": lat, "lon": lon}


def valid_coords(lat, lon) -> tuple[float, float]:
    lat, lon = float(lat), float(lon)
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):   # also rejects NaN and infinity
        raise ValueError("Coordinates out of range")
    return lat, lon


def fetch(lat: float, lon: float) -> dict:
    cfg = load_config()["weather"]
    lat, lon = valid_coords(lat, lon)
    key, now = (round(lat, 2), round(lon, 2)), time.time()
    if key in _CACHE and now - _CACHE[key][0] < cfg["cache_minutes"] * 60:
        return _CACHE[key][1]
    q = urllib.parse.urlencode({"latitude": key[0], "longitude": key[1], "daily": ",".join(DAILY),
                                "past_days": cfg["past_days"], "forecast_days": cfg["forecast_days"],
                                "timezone": "auto"})
    req = urllib.request.Request(f"{URL}?{q}", headers={"User-Agent": "REVIVE-FYP/1.0"})
    # fixed https host built in code (never from user input), so no file:// or SSRF route exists
    with urllib.request.urlopen(req, timeout=cfg.get("timeout_s", 8)) as r:  # nosec B310
        data = json.loads(r.read().decode("utf-8"))
    if "daily" not in data:
        raise ValueError(data.get("reason", "unexpected response"))
    if len(_CACHE) >= _CACHE_MAX:
        for k in sorted(_CACHE, key=lambda k: _CACHE[k][0])[: _CACHE_MAX // 4]:
            _CACHE.pop(k, None)
    _CACHE[key] = (now, data)
    return data


def _at(arr, i):
    try:
        v = arr[i]
        return None if v is None else float(v)
    except (IndexError, TypeError, ValueError):
        return None


def assess(data: dict, today: str | None = None) -> dict:
    rules = load_config()["weather"]["lost_day_rules"]
    d = data["daily"]
    if today is None:
        offset = int(data.get("utc_offset_seconds", 0))
        today = (datetime.now(timezone.utc) + timedelta(seconds=offset)).date().isoformat()
    days = []
    for i, t in enumerate(d["time"]):
        rain, tmax = _at(d.get("precipitation_sum"), i), _at(d.get("temperature_2m_max"), i)
        tmin, wind = _at(d.get("temperature_2m_min"), i), _at(d.get("wind_speed_10m_max"), i)
        why = []
        if rain is not None and rain >= rules["rain_mm"]:
            why.append(f"rain {rain:.0f} mm")
        if wind is not None and wind >= rules["wind_kmh"]:
            why.append(f"wind {wind:.0f} km/h")
        if tmax is not None and tmax >= rules["heat_c"]:
            why.append(f"heat {tmax:.0f} \u00b0C")
        if tmin is not None and tmin <= rules["cold_c"]:
            why.append(f"frost risk {tmin:.0f} \u00b0C")
        days.append({"date": t[:10], "rain_mm": rain, "tmax": tmax, "tmin": tmin, "wind_kmh": wind,
                     "lost": bool(why), "reasons": why})
    past = [x for x in days if x["date"] < today]
    ahead = [x for x in days if x["date"] >= today]
    for i, x in enumerate(ahead):
        x["offset"] = i
    return {"available": True, "today": today, "past": past, "forecast": ahead,
            "lost_past": sum(x["lost"] for x in past), "lost_forecast": sum(x["lost"] for x in ahead),
            "lost_forecast_offsets": [x["offset"] for x in ahead if x["lost"]], "rules": rules,
            "source": "Open-Meteo (open-meteo.com), CC BY 4.0"}


def outlook(lat: float, lon: float, name: str | None = None) -> dict:
    try:
        out = assess(fetch(lat, lon))
    except Exception as exc:  # offline, blocked or provider error: the app carries on
        out = {"available": False, "reason": f"Live weather unavailable ({exc.__class__.__name__}). "
                                             "Enter weather days manually."}
    out["location"] = {"name": name, "lat": lat, "lon": lon}
    return out


def lost_since(assessment: dict, since_iso: str) -> list[dict]:
    """Observed lost days from `since` (inclusive) up to yesterday."""
    if not assessment.get("available"):
        return []
    return [d for d in assessment["past"] if d["date"] >= since_iso[:10] and d["lost"]]
