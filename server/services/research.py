"""Destination research via Open-Meteo (geocoding + forecast). No API key required; free for non-commercial use."""
import logging
import time
from datetime import date
from typing import Any, Optional

import httpx

log = logging.getLogger("tripmate.research")
_cache: dict[str, tuple[float, Any]] = {}
TTL = 1800

WMO = {0: "Clear sky", 1: "Mostly clear", 2: "Partly cloudy", 3: "Overcast", 45: "Fog", 48: "Rime fog",
       51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle", 61: "Light rain", 63: "Rain", 65: "Heavy rain",
       71: "Light snow", 73: "Snow", 75: "Heavy snow", 80: "Rain showers", 81: "Rain showers", 82: "Violent showers",
       95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Thunderstorm with hail"}


async def _get(url: str, params: dict) -> dict:
    async with httpx.AsyncClient(timeout=8) as c:
        r = await c.get(url, params=params)
        r.raise_for_status()
        return r.json()


async def overview(destination: str, start: date, end: date) -> dict[str, Any]:
    key = f"{destination.lower()}|{start}|{end}"
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < TTL:
        return hit[1]
    out: dict[str, Any] = {"destination": destination, "location": None, "weather": None,
                           "attribution": "Weather & geocoding: Open-Meteo.com (CC BY 4.0). Map: © OpenStreetMap contributors.",
                           "errors": []}
    try:
        g = await _get("https://geocoding-api.open-meteo.com/v1/search",
                       {"name": destination, "count": 1, "language": "en", "format": "json"})
        r = (g.get("results") or [None])[0]
        if not r:
            out["errors"].append(f"Couldn't find “{destination}” on the map. Try a more specific place name.")
        else:
            out["location"] = {"name": r.get("name"), "country": r.get("country"), "admin": r.get("admin1"),
                               "lat": r["latitude"], "lon": r["longitude"]}
            try:
                f = await _get("https://api.open-meteo.com/v1/forecast", {
                    "latitude": r["latitude"], "longitude": r["longitude"], "timezone": "auto", "forecast_days": 16,
                    "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"})
                d = f["daily"]
                days = [{"date": d["time"][i], "summary": WMO.get(d["weather_code"][i], "—"),
                         "max_c": d["temperature_2m_max"][i], "min_c": d["temperature_2m_min"][i],
                         "rain_chance": d["precipitation_probability_max"][i]} for i in range(len(d["time"]))]
                in_trip = [x for x in days if start.isoformat() <= x["date"] <= end.isoformat()]
                out["weather"] = {"days": in_trip or days[:7], "covers_trip": bool(in_trip),
                                  "note": None if in_trip else
                                  "Your trip dates are beyond the 16-day forecast window, so this is the current outlook for the destination, not a forecast for your trip."}
            except Exception as exc:  # noqa: BLE001
                log.warning("Weather lookup failed: %s", exc)
                out["errors"].append("Weather is unavailable right now (couldn't reach the weather service).")
    except Exception as exc:  # noqa: BLE001
        log.warning("Geocoding failed: %s", exc)
        out["errors"].append("Map and weather are unavailable right now (couldn't reach the location service).")
    if not out["errors"]:
        _cache[key] = (time.time(), out)
    return out
