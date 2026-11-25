"""Destination research via OpenStreetMap Nominatim, Photon, and Open-Meteo.
No API key required; free for non-commercial use.
"""
import asyncio
from collections import Counter
from datetime import date
import hashlib
import json
import logging
import math
import os
import re
import time
from typing import Any, Optional

import httpx

from server.services.realtime import publish

log = logging.getLogger("tripmate.research")

_cache: dict[str, tuple[float, Any]] = {}
_geocode_cache: dict[str, Optional[dict]] = {}
_geocode_miss_cache: dict[str, tuple[float, str]] = {}
_weather_cache: dict[str, tuple[float, Any]] = {}
_llm_validation_cache: dict[str, list[str]] = {}
_active_background_tasks: set[str] = set()

TTL = 1800
MISS_TTL = 86400  # 24 hours

_nominatim_last_call = 0.0
_nominatim_blocked_until = 0.0
_USER_AGENT = "TripMate-Travel-Planner/1.0 (https://tripmate.app; info@tripmate.app)"

WMO = {
    0: "Clear sky", 1: "Mostly clear", 2: "Partly cloudy", 3: "Overcast", 45: "Fog", 48: "Rime fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle", 61: "Light rain", 63: "Rain", 65: "Heavy rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow", 80: "Rain showers", 81: "Rain showers", 82: "Violent showers",
    95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Thunderstorm with hail"
}

GENERIC_WORDS = [
    "dining hall", "food court", "shopping center", "shopping centre", "night market", "flea market",
    "mosque", "masjid", "temple", "mandir", "church", "cathedral", "shrine", "synagogue",
    "restaurant", "bistro", "cafe", "café", "diner", "dhaba", "bakery", "bar",
    "emporium", "bazaar", "bazar", "market", "mart", "mall",
    "museum", "gallery", "exhibition",
    "garden", "gardens", "park", "sanctuary", "zoo",
    "palace", "fort", "castle", "monument", "memorial",
    "ashram", "complex", "center", "centre", "square", "plaza",
    "lake", "river", "bridge", "beach", "ghat", "hill", "peak", "valley",
    "hotel", "resort", "hostel", "station"
]

STANDALONE_CATEGORIES = {
    "lunch", "dinner", "breakfast", "brunch", "farewell dinner", "snacks", "drinks", "meal",
    "history", "architecture", "local culture", "culture", "recreation", "leisure", "heritage",
    "nature", "adventure", "arrival", "departure", "return", "overview", "tips", "notes",
    "stay", "transport", "shopping", "exploration", "panoramic vistas", "coastal escape",
    "spiritual heights", "souvenirs and departure", "adventure and history"
}

CLAUSE_VERBS = re.compile(
    r"\b(?:is|are|was|were|has|have|had|will|would|can|could|should|transforms|offers|features|serves|provides|opens|closes|built|located|situated|famous|known|experience|enjoy|head to|visit|explore|walk across|take a trip)\b",
    re.IGNORECASE
)

DETERMINERS_START = re.compile(
    r"^(?:this|that|these|those|some|any|all|every|each|another|a|an|the)\s+",
    re.IGNORECASE
)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance in kilometers between two lat/lon coordinates."""
    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _compute_viewbox(lat: float, lon: float, radius_km: float = 30.0) -> str:
    """Compute Nominatim viewbox (min_lon, max_lat, max_lon, min_lat) for radius_km around lat, lon."""
    delta_lat = radius_km / 111.0
    cos_lat = max(math.cos(math.radians(lat)), 0.01)
    delta_lon = radius_km / (111.0 * cos_lat)
    return f"{lon - delta_lon:.5f},{lat + delta_lat:.5f},{lon + delta_lon:.5f},{lat - delta_lat:.5f}"


def _generate_name_variants(name: str) -> list[str]:
    """Generate clean variants of a landmark name by stripping generic terms, articles, and common spellings."""
    variants = []
    clean = re.sub(r"^(?:the|a|an)\s+", "", name.strip().strip("'\".,;:!?-*"), flags=re.I).strip()
    if clean:
        variants.append(clean)

    for gw in GENERIC_WORDS:
        pattern = re.compile(rf"\b{re.escape(gw)}\b", re.IGNORECASE)
        if pattern.search(clean):
            stripped = pattern.sub("", clean)
            stripped = re.sub(r"\s+", " ", stripped).strip(" ,.-")
            if len(stripped) > 2 and stripped.lower() not in [v.lower() for v in variants]:
                variants.append(stripped)

    # Spelling variants
    for v in list(variants):
        low = v.lower()
        if "saiyyed" in low:
            variants.append(re.sub(r"\bsaiyyed\b", "Saiyad", v, flags=re.I))
            variants.append(re.sub(r"\bsaiyyed\b", "Sayed", v, flags=re.I))
            variants.append(re.sub(r"\bsaiyyed\b", "Syed", v, flags=re.I))
        elif "saiyad" in low:
            variants.append(re.sub(r"\bsaiyad\b", "Saiyyed", v, flags=re.I))
        if "bazaar" in low:
            variants.append(re.sub(r"\bbazaar\b", "Bazar", v, flags=re.I))
        elif "bazar" in low:
            variants.append(re.sub(r"\bbazar\b", "Bazaar", v, flags=re.I))
        if "chowk" in low:
            variants.append(re.sub(r"\bchowk\b", "Chawk", v, flags=re.I))
        if "mt." in low:
            variants.append(re.sub(r"\bmt\.\s*", "Mount ", v, flags=re.I))
        if "st." in low:
            variants.append(re.sub(r"\bst\.\s*", "Saint ", v, flags=re.I))

    seen = set()
    final_variants = []
    for var in variants:
        v_low = var.lower().strip()
        if v_low and v_low not in seen and len(v_low) > 1:
            seen.add(v_low)
            final_variants.append(var.strip())

    return final_variants


def _names_resemble(query: str, candidate_name: str) -> bool:
    """Sanity check that candidate name reasonably resembles the queried stop (reject unrelated fuzzy matches)."""
    q_tokens = set(re.findall(r"\w+", query.lower()))
    c_tokens = set(re.findall(r"\w+", candidate_name.lower()))

    generic_set = {
        "the", "a", "an", "and", "of", "in", "at", "to", "for", "on", "de", "la", "le",
        "hall", "dining", "restaurant", "hotel", "mosque", "temple", "museum", "garden", "market"
    }
    q_key = {t for t in q_tokens if t not in generic_set and len(t) > 2}
    c_key = {t for t in c_tokens if t not in generic_set and len(t) > 2}

    if not q_key:
        return True

    for qt in q_key:
        if qt in c_key:
            return True
        for ct in c_key:
            if qt in ct or ct in qt:
                return True
            if abs(len(qt) - len(ct)) <= 2 and len(qt) >= 4 and len(ct) >= 4:
                if qt[:3] == ct[:3] and qt[-2:] == ct[-2:]:
                    return True

    return False


async def _throttle_nominatim() -> bool:
    """Enforce max ~1 request per second for Nominatim policy. Returns False if currently blocked."""
    global _nominatim_last_call, _nominatim_blocked_until
    now = time.time()
    if now < _nominatim_blocked_until:
        return False
    elapsed = now - _nominatim_last_call
    if elapsed < 1.05:
        await asyncio.sleep(1.05 - elapsed)
    _nominatim_last_call = time.time()
    return True


def invalidate_cache(destination: Optional[str] = None) -> None:
    """Invalidate research cache.
    If destination is provided, clear entries starting with that destination name; otherwise clear all.
    """
    global _cache, _geocode_cache, _geocode_miss_cache, _llm_validation_cache
    if destination:
        prefix = destination.lower().strip()
        _cache = {k: v for k, v in _cache.items() if not k.startswith(prefix)}
        _geocode_cache = {k: v for k, v in _geocode_cache.items() if not k.startswith(prefix)}
        _geocode_miss_cache = {k: v for k, v in _geocode_miss_cache.items() if not k.startswith(prefix)}
    else:
        _cache.clear()
        _geocode_cache.clear()
        _geocode_miss_cache.clear()
        _llm_validation_cache.clear()


def extract_locations_from_itinerary(days_data: list[dict], max_candidates: int = 25, destination: Optional[str] = None, raw_plan: Optional[str] = None) -> list[str]:
    """Extract candidate location names from itinerary days using structured places first, then robust fallback rules."""
    if isinstance(max_candidates, str):
        destination = max_candidates
        max_candidates = 25
    # 1. Primary: Check for structured places on day objects
    structured_candidates: list[str] = []
    for day in days_data or []:
        for place in day.get("places", []) or []:
            if isinstance(place, dict) and place.get("name"):
                name = place["name"].strip()
                if len(name) > 2 and name not in structured_candidates:
                    structured_candidates.append(name)
        # Check structured activities
        for act in day.get("activities", []) or []:
            if isinstance(act, dict):
                p_obj = act.get("place")
                if isinstance(p_obj, dict) and p_obj.get("name"):
                    n = p_obj["name"].strip()
                    if len(n) > 2 and n not in structured_candidates:
                        structured_candidates.append(n)
                for key in ("location", "name", "address"):
                    val = act.get(key)
                    if isinstance(val, str) and len(val.strip()) > 2 and val.strip() not in structured_candidates:
                        structured_candidates.append(val.strip())

    if structured_candidates:
        return structured_candidates[:max_candidates]

    # 2. Comprehensive Fallback Extractor (for itineraries without structured places, supporting both bold markdown and plain-text activity descriptions worldwide):
    raw_candidates: list[str] = []
    bold_pattern = re.compile(r"\*\*([A-Za-z0-9\s'’\-–—.,/&:]+?)\*\*", re.DOTALL)

    _place_suffixes = (
        "Museum|Palace|Castle|Temple|Shrine|Church|Cathedral|Basilica|Mosque|Tower|Bridge|"
        "Park|Garden|Gardens|Beach|Bay|Lake|Falls|River|Canal|Market|Bazaar|Souk|Square|Plaza|"
        "Piazza|Station|Fort|Fortress|Monument|Memorial|Center|Centre|Gallery|Theater|Theatre|"
        "Stadium|Arena|Aquarium|Zoo|Sanctuary|Harbor|Harbour|Pier|Quay|Promenade|District|Quarter|"
        "Hill|Mountain|Peak|Canyon|Gorge|Valley|Island|Point|Viewpoint|Overlook|Observatory|SkyPark|"
        "Crossing|Ashram|Mahal|Mandir|Ghat|Pagoda|Wat|Gate|Arch|Steps|Colosseum|Forum|Acropolis|"
        "Pyramids|Ruins|Cemetery|Street|Avenue|Boulevard|Stepwell|House"
    )
    _standalone_landmarks_re = re.compile(
        r"\b(Colosseum|Roman Forum|Pantheon|Parthenon|Acropolis|Sagrada Familia|Alhambra|Petra|Machu Picchu|Taj Mahal|Angkor Wat|Stonehenge|Big Ben|London Eye|Burj Khalifa|Chichen Itza|Christ the Redeemer|Louvre|Eiffel Tower|Trevi Fountain|Sydney Opera House)\b",
        re.IGNORECASE,
    )
    _suffix_place_re = re.compile(
        rf"\b([A-Z0-9][a-zA-Z0-9'’\-]*(?:\s+(?:of|de|del|du|la|le|des|da|di|the|[A-Z0-9][a-zA-Z0-9'’\-]*)){{0,4}}\s+(?:{_place_suffixes}))\b"
    )
    _action_place_re = re.compile(
        r"\b(?:visit|explore|tour|head to|walk(?: to| around| through)?|stroll(?: through| around)?|wander(?: through| around)?|stop by|check out|discover|relax at|dinner at|lunch at|breakfast at|brunch at|drinks at|meal at|morning at|afternoon at|evening at|sunset at|hike up|ascend|climb|admire|see)\s+(?:the\s+|a\s+|an\s+)?([A-Z0-9][a-zA-Z0-9'’\-]+(?:\s+(?:of|de|del|du|la|le|des|da|di|the|[A-Z0-9][a-zA-Z0-9'’\-]+)){0,3})",
        re.IGNORECASE,
    )
    _bullet_place_re = re.compile(
        r"(?:^|\n)\s*[-*+•]\s*(?:(?:Morning|Afternoon|Evening|Night)\s*[:\-–—]\s*)?([A-Za-z0-9\s'’\-–—/&]+?)(?:\s*[:\-–—]|\s*\(|\s*\n|\Z)"
    )
    _prefix_strip_re = re.compile(
        r"^(?:Visit|Explore|Tour|Head to|Walk(?: to| around| through)?|Stroll(?: through| around)?|Wander(?: through| around)?|Stop by|Check out|Discover|Relax at|Dinner at|Lunch at|Breakfast at|Brunch at|Drinks at|Meal at|Morning at|Afternoon at|Evening at|Night at|Sunset at|See|Climb|Ascend|Admire|Spend your \w+ at)\s+(?:the\s+|a\s+|an\s+)?",
        re.IGNORECASE,
    )
    _days_months_re = re.compile(
        r"\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|January|February|March|April|May|June|July|August|September|October|November|December|Day\s*\d+)\b",
        re.IGNORECASE,
    )

    dest_clean = (destination or "").split(",")[0].strip().lower()

    def _clean_and_add(raw_item: str) -> None:
        if not raw_item:
            return
        parts = re.split(r"\s+(?:and|&)\s+", raw_item)
        for part in parts:
            clean = _prefix_strip_re.sub("", part.strip(" :.-–—*'\"(),")).strip()
            clean = re.sub(r"^(?:the|a|an)\s+", "", clean, flags=re.I).strip()
            clean = re.sub(r"\s*\([^)]*\)", "", clean).strip()
            clean = re.split(r"\s*[:\-–—]\s*", clean)[0].strip()

            if not clean or len(clean) <= 2 or len(clean) > 45:
                continue
            words = clean.split()
            if len(words) > 6:
                continue
            if not clean[0].isupper() and not clean[0].isdigit():
                continue
            low = clean.lower()
            if dest_clean and (low == dest_clean or (destination and low == destination.lower())):
                continue
            if low in STANDALONE_CATEGORIES:
                continue
            if any(c in clean for c in ["₹", "$", "€", "£", "%"]):
                continue
            if _days_months_re.search(clean):
                continue
            if DETERMINERS_START.search(clean):
                continue
            if CLAUSE_VERBS.search(clean):
                continue
            if low.startswith(("note", "estimate", "approx", "entry", "activity", "activities", "budget", "flight", "check-in", "checkout", "transfer")):
                continue
            raw_candidates.append(clean)

    for day in days_data or []:
        # Intentionally SKIP day.get("title") — day headings are thematic, never place names!
        contents = [s.get("content", "") for s in (day.get("sections", []) or [])]
        for act in day.get("activities", []) or []:
            if isinstance(act, str):
                contents.append(act)
            elif isinstance(act, dict):
                for k in ("description", "text", "summary"):
                    if act.get(k):
                        contents.append(act[k])
        if day.get("intro"):
            contents.append(day.get("intro"))

        for content in contents:
            if not content:
                continue
            # 1. Bold text
            for m in bold_pattern.finditer(content):
                _clean_and_add(m.group(1))
            # 2. Bullet starts
            for m in _bullet_place_re.finditer(content):
                _clean_and_add(m.group(1))
            # 3. Capitalized proper nouns with place suffixes
            for m in _suffix_place_re.finditer(content):
                _clean_and_add(m.group(1))
            # 4. Standalone world landmarks
            for m in _standalone_landmarks_re.finditer(content):
                _clean_and_add(m.group(1))
            # 5. Action triggers (visit/explore/etc.)
            for m in _action_place_re.finditer(content):
                words = m.group(1).split()
                valid_words = []
                for w in words:
                    if w[0].isupper() or w.lower() in ("of", "de", "del", "du", "la", "le", "des", "da", "di"):
                        valid_words.append(w)
                    else:
                        break
                if valid_words:
                    _clean_and_add(" ".join(valid_words))

    # 3. Fallback to raw_plan markdown if structured days yielded no places
    if not raw_candidates and raw_plan:
        for m in bold_pattern.finditer(raw_plan):
            _clean_and_add(m.group(1))
        for m in _bullet_place_re.finditer(raw_plan):
            _clean_and_add(m.group(1))
        for m in _suffix_place_re.finditer(raw_plan):
            _clean_and_add(m.group(1))
        for m in _standalone_landmarks_re.finditer(raw_plan):
            _clean_and_add(m.group(1))
        for m in _action_place_re.finditer(raw_plan):
            words = m.group(1).split()
            valid_words = [w for w in words if w[0].isupper() or w.lower() in ("of", "de", "del", "du", "la", "le", "des", "da", "di")]
            if valid_words:
                _clean_and_add(" ".join(valid_words))

    # Deduplicate while preserving order
    seen = set()
    unique: list[str] = []
    for c in raw_candidates:
        clean = re.sub(r"\s+", " ", c).strip(" ,.-*")
        low = clean.lower()
        if low not in seen and len(clean) > 2:
            seen.add(low)
            unique.append(clean)

    # Filter redundant single-word substrings when a compound name is present (e.g. "Louvre" vs "Louvre Museum")
    filtered: list[str] = []
    for item in unique:
        low_item = item.lower()
        if any(low_item != other.lower() and low_item in other.lower().split() for other in unique):
            continue
        filtered.append(item)

    limit = min(max_candidates, 15) if max_candidates else 15
    return filtered[:limit] if filtered else unique[:limit]


async def validate_candidate_places_with_llm(destination: str, candidates: list[str]) -> list[str]:
    """Safety net: validate candidates with ONE batched LLM call to ensure they are real, specific, mappable places."""
    if not candidates:
        return []

    cache_key = f"{destination.lower()}|{hashlib.md5(json.dumps(sorted(candidates)).encode()).hexdigest()}"
    if cache_key in _llm_validation_cache:
        return _llm_validation_cache[cache_key]

    try:
        from server.ai.client import llm_json
        from server.ai.gateway import PRIORITY_DEFERRABLE
        system = "You are a travel geographer. Review candidate place names from an itinerary and filter out non-places."
        prompt = (
            f"Given the destination '{destination}', review the following list of candidate names extracted from an itinerary.\n"
            f"Return ONLY the entries that are real, specific, mappable places (e.g. landmarks, attractions, temples, mosques, churches, monuments, museums, restaurants, cafes, markets, parks, lakes, bridges, distinct neighborhoods).\n"
            f"Reject any entries that are non-places, section headings, generic concepts, activities, or descriptive fragments (e.g. 'History', 'Culture', 'Shopping', 'Local Food').\n"
            f"Candidates:\n{json.dumps(candidates)}\n\n"
            f"Respond with JSON in this format only:\n"
            f'{{"valid_places": ["Exact Name 1", "Exact Name 2"]}}'
        )
        res = await llm_json(system, prompt, feature="map_place_validation", priority=PRIORITY_DEFERRABLE)
        if isinstance(res, dict) and isinstance(res.get("valid_places"), list):
            valid = [p for p in res["valid_places"] if p in candidates or any(p.lower() == c.lower() for c in candidates)]
            _llm_validation_cache[cache_key] = valid
            return valid
    except Exception as exc:
        log.warning("LLM candidate validation failed for %s: %s", destination, exc)

    # Fallback to candidates if LLM call fails
    return candidates


async def _get(url: str, params: dict, headers: Optional[dict] = None) -> dict:
    req_headers = {"User-Agent": _USER_AGENT, **(headers or {})}
    async with httpx.AsyncClient(timeout=10, headers=req_headers) as c:
        r = await c.get(url, params=params)
        r.raise_for_status()
        return r.json()


def _score_nominatim_candidate(query: str, item: dict) -> float:
    """Score Nominatim candidate by exact name, type, importance, and country/region hint."""
    score = 0.0
    imp = float(item.get("importance") or 0.0)
    score += imp * 10.0

    name = (item.get("name") or "").lower()
    disp = (item.get("display_name") or "").lower()
    q_low = query.lower().strip()

    if name == q_low or disp.startswith(q_low):
        score += 20.0
    elif q_low in disp:
        score += 10.0

    t = (item.get("type") or "").lower()
    c = (item.get("class") or "").lower()
    if t in ("city", "town", "administrative", "state", "province", "country"):
        score += 12.0
    elif t in ("village", "island", "municipality"):
        score += 6.0
    elif c == "place":
        score += 5.0

    if "," in query:
        parts = [p.strip().lower() for p in query.split(",")[1:] if p.strip()]
        for p in parts:
            if p in disp:
                score += 30.0

    return score


def _score_open_meteo_candidate(query: str, item: dict) -> float:
    """Score Open-Meteo candidate by exact match, population, and country hint."""
    score = 0.0
    name = (item.get("name") or "").lower()
    q_low = query.lower().strip()

    if name == q_low:
        score += 20.0
    elif q_low in name:
        score += 8.0

    pop = float(item.get("population") or 0.0)
    if pop > 50000:
        score += 10.0
    elif pop > 5000:
        score += 5.0

    fcode = (item.get("feature_code") or "").upper()
    if fcode in ("PPLC", "PPLA", "PPLA2", "ADM1"):
        score += 10.0

    if "," in query:
        parts = [p.strip().lower() for p in query.split(",")[1:] if p.strip()]
        country = (item.get("country") or "").lower()
        admin = (item.get("admin1") or "").lower()
        for p in parts:
            if p in country or p in admin:
                score += 30.0

    return score


async def geocode_place(query: str) -> Optional[dict]:
    """Geocode a place using OpenStreetMap Nominatim as primary and Open-Meteo as fallback."""
    global _nominatim_blocked_until
    q_clean = query.strip()
    if not q_clean:
        return None

    cache_key = q_clean.lower()
    if cache_key in _geocode_cache:
        return _geocode_cache[cache_key]

    # 1. Primary: Nominatim
    try:
        if await _throttle_nominatim():
            data = await _get(
                "https://nominatim.openstreetmap.org/search",
                {"q": q_clean, "format": "json", "limit": 5, "addressdetails": 1},
            )
            if isinstance(data, list) and len(data) > 0:
                scored = sorted(data, key=lambda it: _score_nominatim_candidate(q_clean, it), reverse=True)
                best = scored[0]
                addr = best.get("address", {})
                country = addr.get("country")
                admin = addr.get("state") or addr.get("county") or addr.get("region")
                name = best.get("name") or q_clean
                place_type = best.get("type", "")
                display = best.get("display_name") or f"{name}, {country}" if country else name
                res = {
                    "name": name,
                    "label": f"{name} ({country})" if country and country.lower() not in name.lower() else name,
                    "display_name": display,
                    "country": country,
                    "admin": admin,
                    "type": place_type,
                    "lat": float(best["lat"]),
                    "lon": float(best["lon"]),
                }
                _geocode_cache[cache_key] = res
                return res
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (403, 429):
            _nominatim_blocked_until = time.time() + 3600
            log.warning("Nominatim returned %d for '%s'. Tripping circuit breaker for 1h.", exc.response.status_code, q_clean)
    except Exception as exc:  # noqa: BLE001
        log.warning("Nominatim geocoding failed for '%s': %s", q_clean, exc)

    # 2. Fallback: Open-Meteo
    try:
        data = await _get(
            "https://geocoding-api.open-meteo.com/v1/search",
            {"name": q_clean, "count": 5, "language": "en", "format": "json"},
        )
        results = data.get("results") or []
        if results:
            scored = sorted(results, key=lambda it: _score_open_meteo_candidate(q_clean, it), reverse=True)
            best = scored[0]
            name = best.get("name") or q_clean
            country = best.get("country")
            admin = best.get("admin1")
            res = {
                "name": name,
                "label": f"{name} ({country})" if country and country.lower() not in name.lower() else name,
                "display_name": f"{name}, {admin}, {country}" if admin and country else f"{name}, {country}" if country else name,
                "country": country,
                "admin": admin,
                "type": "city",
                "lat": float(best["latitude"]),
                "lon": float(best["longitude"]),
            }
            _geocode_cache[cache_key] = res
            return res
    except Exception as exc:  # noqa: BLE001
        log.warning("Open-Meteo fallback geocoding failed for '%s': %s", q_clean, exc)

    # 3. Fallback: Photon (free, unauthenticated, allows cloud IPs)
    try:
        data = await _get("https://photon.komoot.io/api/", {"q": q_clean, "limit": 5})
        features = data.get("features") or [] if isinstance(data, dict) else []
        if features:
            best = features[0]
            coords = best.get("geometry", {}).get("coordinates", [])
            props = best.get("properties", {})
            if len(coords) >= 2:
                p_name = props.get("name") or q_clean
                country = props.get("country")
                admin = props.get("state") or props.get("city")
                res = {
                    "name": p_name,
                    "label": f"{p_name} ({country})" if country and country.lower() not in p_name.lower() else p_name,
                    "display_name": f"{p_name}, {admin}, {country}" if admin and country else f"{p_name}, {country}" if country else p_name,
                    "country": country,
                    "admin": admin,
                    "type": props.get("type", "city"),
                    "lat": float(coords[1]),
                    "lon": float(coords[0]),
                }
                _geocode_cache[cache_key] = res
                return res
    except Exception as exc:  # noqa: BLE001
        log.warning("Photon fallback geocoding failed for '%s': %s", q_clean, exc)

    # 4. Fallback: WeatherAPI search (authenticated key, works on cloud hosts where Nominatim/Open-Meteo fail)
    api_key = os.getenv("WEATHERAPI_KEY")
    if api_key:
        try:
            results = await _get("https://api.weatherapi.com/v1/search.json", {"key": api_key, "q": q_clean})
            if isinstance(results, list) and results:
                best = results[0]
                name = best.get("name") or q_clean
                country = best.get("country")
                admin = best.get("region")
                res = {
                    "name": name,
                    "label": f"{name} ({country})" if country and country.lower() not in name.lower() else name,
                    "display_name": f"{name}, {admin}, {country}" if admin and country else f"{name}, {country}" if country else name,
                    "country": country,
                    "admin": admin,
                    "type": "city",
                    "lat": float(best["lat"]),
                    "lon": float(best["lon"]),
                }
                _geocode_cache[cache_key] = res
                return res
        except Exception as exc:  # noqa: BLE001
            log.warning("WeatherAPI fallback geocoding failed for '%s': %s", q_clean, exc)

    _geocode_cache[cache_key] = None
    return None


async def _query_photon(query: str, lat: float, lon: float) -> list[dict]:
    """Query Photon API (https://photon.komoot.io/api/) with lat/lon bias near destination."""
    try:
        data = await _get(
            "https://photon.komoot.io/api/",
            {"q": query, "lat": lat, "lon": lon, "limit": 5}
        )
        features = data.get("features") or [] if isinstance(data, dict) else []
        results = []
        for f in features:
            geom = f.get("geometry") or {}
            props = f.get("properties") or {}
            coords = geom.get("coordinates")
            if coords and len(coords) >= 2:
                p_name = props.get("name") or query
                results.append({
                    "name": p_name,
                    "country": props.get("country"),
                    "admin": props.get("state") or props.get("city"),
                    "lat": float(coords[1]),
                    "lon": float(coords[0]),
                    "type": props.get("type", "landmark"),
                    "display_name": p_name,
                })
        return results
    except Exception as exc:
        log.debug("Photon query '%s' failed: %s", query, exc)
    return []


async def _query_open_meteo_geocoding(query: str, dest_lat: float, dest_lon: float, max_dist_km: float = 150.0) -> list[dict]:
    """Query Open-Meteo Geocoding API (https://geocoding-api.open-meteo.com/v1/search) and filter near destination."""
    try:
        data = await _get(
            "https://geocoding-api.open-meteo.com/v1/search",
            {"name": query, "count": 10, "language": "en", "format": "json"}
        )
        results = data.get("results") or [] if isinstance(data, dict) else []
        matched = []
        for item in results:
            lat, lon = float(item["latitude"]), float(item["longitude"])
            dist = haversine_km(dest_lat, dest_lon, lat, lon)
            if dist <= max_dist_km:
                p_name = item.get("name") or query
                matched.append({
                    "name": p_name,
                    "country": item.get("country"),
                    "admin": item.get("admin1"),
                    "lat": lat,
                    "lon": lon,
                    "distance_km": round(dist, 1),
                    "type": item.get("feature_code", "landmark"),
                    "display_name": p_name,
                })
        return matched
    except Exception as exc:
        log.debug("Open-Meteo geocoding query '%s' failed: %s", query, exc)
    return []


def _persist_itinerary_coordinates(itinerary_id: int, new_coords: dict[str, dict]) -> None:
    """Persist newly resolved coordinates into the itinerary.days JSON column in DB."""
    if not itinerary_id or not new_coords:
        return
    try:
        from server.db import SessionLocal
        from server.models import Itinerary
        from sqlalchemy.orm.attributes import flag_modified
        with SessionLocal() as session:
            it = session.get(Itinerary, itinerary_id)
            if it:
                days_dict = dict(it.days or {})
                existing = dict(days_dict.get("cached_coordinates") or {})
                updated = False
                for k, v in new_coords.items():
                    norm_k = k.lower().strip()
                    if norm_k not in existing or existing[norm_k] != v:
                        existing[norm_k] = v
                        updated = True
                if updated:
                    days_dict["cached_coordinates"] = existing
                    it.days = days_dict
                    flag_modified(it, "days")
                    session.commit()
                    log.info("Persisted %d cached coordinates to itinerary %d", len(existing), itinerary_id)
    except Exception as exc:
        log.warning("Failed to persist cached coordinates to itinerary %d: %s", itinerary_id, exc)


async def _approximate_location_with_gemini(
    name: str,
    dest_city: str,
    dest_country: Optional[str] = None
) -> Optional[dict]:
    """Optional last resort: ask existing Gemini model (llm_json) for approximate coordinates of well-known places."""
    try:
        from server.ai.client import llm_json
        from server.ai.gateway import PRIORITY_SKIPPABLE
        country_str = f", {dest_country}" if dest_country else ""
        system = "You are a precise geographic locator assistant. Respond with JSON only."
        prompt = (
            f"You are a geographic locator. What are the approximate latitude and longitude coordinates for "
            f"the landmark, place, restaurant, or attraction '{name}' in or near {dest_city}{country_str}?\n"
            f"Respond with JSON only in this exact format:\n"
            f'{{"found": true, "name": "{name}", "lat": 23.0337, "lon": 72.5645, "explanation": "located in ..."}}\n'
            f"If the place is unknown, fictitious, or cannot be located, return:\n"
            f'{{"found": false, "name": "{name}", "lat": null, "lon": null, "explanation": "unknown"}}'
        )
        res = await llm_json(system, prompt, feature="map_coordinate_fallback", priority=PRIORITY_SKIPPABLE)
        if isinstance(res, dict) and res.get("found") is True:
            lat = res.get("lat")
            lon = res.get("lon")
            if lat is not None and lon is not None:
                return {
                    "name": res.get("name") or name,
                    "lat": float(lat),
                    "lon": float(lon),
                    "is_approximate": True,
                    "display_name": f"{res.get('name') or name} (approximate location)",
                }
    except Exception as exc:
        log.debug("Gemini location approximation for '%s' failed: %s", name, exc)
    return None


async def _geocode_candidate_within_radius(
    name: str,
    dest_lat: float,
    dest_lon: float,
    dest_city: str,
    dest_country: Optional[str] = None,
    max_dist_km: float = 150.0,
    cached_coords: Optional[dict[str, dict]] = None,
) -> tuple[Optional[dict], Optional[str]]:
    """Geocode an itinerary stop using a multi-tier lookup pipeline with automatic cloud fallbacks,
    stopping at first accepted result. Returns (result_dict, miss_reason).
    """
    global _nominatim_blocked_until
    cache_key = f"{name.lower().strip()}|{dest_city.lower().strip()}|{dest_lat:.2f},{dest_lon:.2f}"

    # 1. Check persistent coordinates from itinerary.days first (0 external network calls)
    variants = _generate_name_variants(name)
    if cached_coords:
        cand_norm = name.lower().strip()
        if cand_norm in cached_coords and cached_coords[cand_norm]:
            c_hit = cached_coords[cand_norm]
            _geocode_cache[cache_key] = c_hit
            return c_hit, None
        for v in variants:
            v_norm = v.lower().strip()
            if v_norm in cached_coords and cached_coords[v_norm]:
                c_hit = cached_coords[v_norm]
                _geocode_cache[cache_key] = c_hit
                return c_hit, None

    if cache_key in _geocode_cache:
        hit = _geocode_cache[cache_key]
        if hit:
            return hit, None

    if cache_key in _geocode_miss_cache:
        ts, reason = _geocode_miss_cache[cache_key]
        if time.time() - ts < MISS_TTL:
            return None, reason

    viewbox = _compute_viewbox(dest_lat, dest_lon, radius_km=30.0)
    outside_dist: Optional[float] = None
    timed_out = False

    # Nominatim bounded searches (Tier a, b, c) — only if Nominatim is not currently throttled/blocked
    if time.time() >= _nominatim_blocked_until:
        # Tier a: Nominatim bounded search with bare place name
        for v in variants[:2]:
            try:
                if not await _throttle_nominatim():
                    break
                data = await _get(
                    "https://nominatim.openstreetmap.org/search",
                    {"q": v, "format": "json", "limit": 5, "addressdetails": 1, "viewbox": viewbox, "bounded": 1}
                )
                if isinstance(data, list) and data:
                    for item in data:
                        lat, lon = float(item["lat"]), float(item["lon"])
                        dist = haversine_km(dest_lat, dest_lon, lat, lon)
                        cand_name = item.get("name") or item.get("display_name") or ""
                        if dist <= max_dist_km:
                            if _names_resemble(v, cand_name):
                                addr = item.get("address", {})
                                res = {
                                    "name": name,
                                    "display_name": item.get("name") or name,
                                    "country": addr.get("country"),
                                    "admin": addr.get("state") or addr.get("county"),
                                    "lat": lat,
                                    "lon": lon,
                                    "distance_km": round(dist, 1),
                                    "is_approximate": False,
                                }
                                _geocode_cache[cache_key] = res
                                return res, None
                        else:
                            outside_dist = dist
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in (403, 429):
                    _nominatim_blocked_until = time.time() + 3600
                    log.warning("Nominatim returned %d for '%s'. Tripping circuit breaker for 1h and using cloud fallback geocoders.", exc.response.status_code, v)
                    break
            except httpx.TimeoutException:
                timed_out = True
            except Exception as exc:
                log.debug("Tier a Nominatim bounded search error for '%s': %s", v, exc)

        # Tier b: Nominatim bounded search with "<name>, <city>"
        if time.time() >= _nominatim_blocked_until:
            for v in variants[:2]:
                q_city = f"{v}, {dest_city}"
                try:
                    if not await _throttle_nominatim():
                        break
                    data = await _get(
                        "https://nominatim.openstreetmap.org/search",
                        {"q": q_city, "format": "json", "limit": 5, "addressdetails": 1, "viewbox": viewbox, "bounded": 1}
                    )
                    if isinstance(data, list) and data:
                        for item in data:
                            lat, lon = float(item["lat"]), float(item["lon"])
                            dist = haversine_km(dest_lat, dest_lon, lat, lon)
                            cand_name = item.get("name") or item.get("display_name") or ""
                            if dist <= max_dist_km:
                                if _names_resemble(v, cand_name):
                                    addr = item.get("address", {})
                                    res = {
                                        "name": name,
                                        "display_name": item.get("name") or name,
                                        "country": addr.get("country"),
                                        "admin": addr.get("state") or addr.get("county"),
                                        "lat": lat,
                                        "lon": lon,
                                        "distance_km": round(dist, 1),
                                        "is_approximate": False,
                                    }
                                    _geocode_cache[cache_key] = res
                                    return res, None
                            else:
                                outside_dist = dist
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code in (403, 429):
                        _nominatim_blocked_until = time.time() + 3600
                        log.warning("Nominatim returned %d for '%s'. Circuit breaker open for 1h.", exc.response.status_code, q_city)
                        break
                except httpx.TimeoutException:
                    timed_out = True
                except Exception as exc:
                    log.debug("Tier b Nominatim city search error for '%s': %s", q_city, exc)

        # Tier c: Name variants with Nominatim bounded
        if time.time() >= _nominatim_blocked_until:
            for v in variants[2:]:
                for q in [v, f"{v}, {dest_city}"]:
                    try:
                        if not await _throttle_nominatim():
                            break
                        data = await _get(
                            "https://nominatim.openstreetmap.org/search",
                            {"q": q, "format": "json", "limit": 5, "addressdetails": 1, "viewbox": viewbox, "bounded": 1}
                        )
                        if isinstance(data, list) and data:
                            for item in data:
                                lat, lon = float(item["lat"]), float(item["lon"])
                                dist = haversine_km(dest_lat, dest_lon, lat, lon)
                                cand_name = item.get("name") or item.get("display_name") or ""
                                if dist <= max_dist_km:
                                    if _names_resemble(v, cand_name):
                                        addr = item.get("address", {})
                                        res = {
                                            "name": name,
                                            "display_name": item.get("name") or name,
                                            "country": addr.get("country"),
                                            "admin": addr.get("state") or addr.get("county"),
                                            "lat": lat,
                                            "lon": lon,
                                            "distance_km": round(dist, 1),
                                            "is_approximate": False,
                                        }
                                        _geocode_cache[cache_key] = res
                                        return res, None
                                else:
                                    outside_dist = dist
                    except httpx.HTTPStatusError as exc:
                        if exc.response.status_code in (403, 429):
                            _nominatim_blocked_until = time.time() + 3600
                            log.warning("Nominatim returned %d. Circuit breaker open for 1h.", exc.response.status_code)
                            break
                    except httpx.TimeoutException:
                        timed_out = True
                    except Exception as exc:
                        log.debug("Tier c Nominatim variant search error for '%s': %s", q, exc)

    # Fallback Tier 1: Photon API with lat/lon bias near destination (free, unauthenticated, allows cloud IPs)
    dest_clean = dest_city.split(",")[0].strip()
    for v in variants:
        queries_to_try = [f"{v}, {dest_clean}", v] if dest_clean.lower() not in v.lower() else [v]
        for q_try in queries_to_try:
            try:
                await asyncio.sleep(0.25)  # polite spacing for cloud requests
                photon_results = await _query_photon(q_try, dest_lat, dest_lon)
                for item in photon_results:
                    lat, lon = item["lat"], item["lon"]
                    dist = haversine_km(dest_lat, dest_lon, lat, lon)
                    cand_name = item.get("name") or item.get("display_name") or ""
                    if dist <= max_dist_km:
                        if _names_resemble(v, cand_name):
                            res = {
                                "name": name,
                                "display_name": item.get("name") or name,
                                "country": item.get("country"),
                                "admin": item.get("admin"),
                                "lat": lat,
                                "lon": lon,
                                "distance_km": round(dist, 1),
                                "is_approximate": False,
                            }
                            _geocode_cache[cache_key] = res
                            return res, None
                    else:
                        outside_dist = dist
            except httpx.TimeoutException:
                timed_out = True
            except Exception as exc:
                log.debug("Tier d Photon search error for '%s': %s", q_try, exc)

    # Fallback Tier 2: Open-Meteo Geocoding API (free, unauthenticated, allows cloud IPs)
    for v in variants[:3]:
        try:
            await asyncio.sleep(0.25)  # polite spacing
            om_results = await _query_open_meteo_geocoding(v, dest_lat, dest_lon, max_dist_km=max_dist_km)
            for item in om_results:
                lat, lon = item["lat"], item["lon"]
                dist = item.get("distance_km") or haversine_km(dest_lat, dest_lon, lat, lon)
                cand_name = item.get("name") or ""
                if dist <= max_dist_km and _names_resemble(v, cand_name):
                    res = {
                        "name": name,
                        "display_name": cand_name or name,
                        "country": item.get("country"),
                        "admin": item.get("admin"),
                        "lat": lat,
                        "lon": lon,
                        "distance_km": round(dist, 1),
                        "is_approximate": False,
                    }
                    _geocode_cache[cache_key] = res
                    return res, None
                else:
                    outside_dist = dist
        except httpx.TimeoutException:
            timed_out = True
        except Exception as exc:
            log.debug("Tier e Open-Meteo search error for '%s': %s", v, exc)
        except Exception as exc:
            log.debug("Tier om Open-Meteo geocoding search error for '%s': %s", v, exc)

    # Tier w: WeatherAPI search (if key configured)
    api_key = os.getenv("WEATHERAPI_KEY")
    if api_key:
        for q_cand in [name, f"{name}, {dest_city}"]:
            try:
                items = await _get("https://api.weatherapi.com/v1/search.json", {"key": api_key, "q": q_cand})
                if isinstance(items, list):
                    for item in items:
                        lat, lon = float(item["lat"]), float(item["lon"])
                        dist = haversine_km(dest_lat, dest_lon, lat, lon)
                        cand_name = item.get("name") or ""
                        if dist <= max_dist_km and _names_resemble(name, cand_name):
                            res = {
                                "name": name,
                                "display_name": cand_name or name,
                                "country": item.get("country"),
                                "admin": item.get("region"),
                                "lat": lat,
                                "lon": lon,
                                "distance_km": round(dist, 1),
                                "is_approximate": False,
                            }
                            _geocode_cache[cache_key] = res
                            return res, None
                        else:
                            outside_dist = dist
            except Exception as exc:
                log.debug("Tier w WeatherAPI search error for '%s': %s", q_cand, exc)

    # Tier e: Optional last resort: ask Gemini model (llm_json) for approximate coordinates
    skipped_for_quota = False
    try:
        from server.ai.gateway import PRIORITY_SKIPPABLE, gateway
        if gateway.is_enabled() and gateway.should_skip_optional(PRIORITY_SKIPPABLE):
            skipped_for_quota = True
            log.info("Skipping Tier-e coordinate approximation for '%s' to conserve AI quota", name)
        else:
            gemini_loc = await _approximate_location_with_gemini(name, dest_city, dest_country)
            if gemini_loc:
                lat, lon = gemini_loc["lat"], gemini_loc["lon"]
                dist = haversine_km(dest_lat, dest_lon, lat, lon)
                if dist <= max_dist_km:
                    res = {
                        "name": name,
                        "display_name": gemini_loc.get("display_name") or f"{name} (approximate location)",
                        "country": dest_country,
                        "admin": None,
                        "lat": lat,
                        "lon": lon,
                        "distance_km": round(dist, 1),
                        "is_approximate": True,
                    }
                    _geocode_cache[cache_key] = res
                    return res, None
                else:
                    outside_dist = dist
    except Exception as exc:
        log.debug("Tier e Gemini search error for '%s': %s", name, exc)

    if skipped_for_quota:
        miss_reason = "Skipped to save AI quota (will retry in background)"
        # Short 30s TTL cache so degraded result is never permanent and is retried
        _geocode_miss_cache[cache_key] = (time.time() - MISS_TTL + 30.0, miss_reason)
        return None, miss_reason
    elif outside_dist is not None:
        miss_reason = f"A match was found but too far from the destination ({round(outside_dist)} km)"
    elif timed_out:
        miss_reason = "Lookup timed out"
    else:
        miss_reason = "Not found in the map database"

    _geocode_miss_cache[cache_key] = (time.time(), miss_reason)
    return None, miss_reason


async def _fetch_weatherapi(lat: float, lon: float, start: date, end: date) -> Optional[dict]:
    """Fallback weather fetch using WeatherAPI.com when Open-Meteo is unavailable or rate-limited."""
    api_key = os.getenv("WEATHERAPI_KEY")
    if not api_key:
        return None

    today = date.today()
    days_to_fetch = min(max((end - today).days + 1, 1), 14)

    url = "https://api.weatherapi.com/v1/forecast.json"
    params = {
        "key": api_key,
        "q": f"{lat:.5f},{lon:.5f}",
        "days": days_to_fetch,
        "aqi": "no",
        "alerts": "no",
    }
    req_headers = {"User-Agent": _USER_AGENT}
    async with httpx.AsyncClient(timeout=10, headers=req_headers) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        data = r.json()

    curr = data.get("current") or {}
    forecast = data.get("forecast") or {}
    fdays = forecast.get("forecastday") or []

    in_trip_days = []
    max_list = []
    min_list = []
    rain_list = []
    wind_list = []
    cond_list = []

    for fd in fdays:
        d_str = fd.get("date")
        if start.isoformat() <= d_str <= end.isoformat():
            day_info = fd.get("day") or {}
            mx = day_info.get("maxtemp_c")
            mn = day_info.get("mintemp_c")
            cond = day_info.get("condition", {}).get("text")
            rain = day_info.get("daily_chance_of_rain")
            wind = day_info.get("maxwind_kph")

            in_trip_days.append({
                "date": d_str,
                "max_c": round(mx, 1) if mx is not None else None,
                "min_c": round(mn, 1) if mn is not None else None,
                "condition": cond or "Not available",
                "rain_chance": rain if rain is not None else None,
            })
            if mx is not None:
                max_list.append(mx)
            if mn is not None:
                min_list.append(mn)
            if rain is not None:
                rain_list.append(rain)
            if wind is not None:
                wind_list.append(wind)
            if cond:
                cond_list.append(cond)

    if in_trip_days and max_list and min_list:
        avg_max = sum(max_list) / len(max_list)
        avg_min = sum(min_list) / len(min_list)
        avg_rain = round(sum(rain_list) / len(rain_list)) if rain_list else None
        avg_wind = round(sum(wind_list) / len(wind_list)) if wind_list else None
        top_cond = Counter(cond_list).most_common(1)[0][0] if cond_list else "Not available"
        date_label = f"{in_trip_days[0]['date']} to {in_trip_days[-1]['date']}"
        total_trip_days = (end - start).days + 1
        note = None if len(in_trip_days) >= total_trip_days else f"Showing forecast for days within the 14-day window ({len(in_trip_days)} of {total_trip_days} days). Future days will update as your trip approaches."

        return {
            "forecast_available": True,
            "forecast_note": note,
            "date_label": date_label,
            "temp_display": f"{round(avg_min)}° / {round(avg_max)}°C avg",
            "avg_high_c": round(avg_max),
            "avg_low_c": round(avg_min),
            "condition": top_cond,
            "humidity": round(curr.get("humidity")) if curr.get("humidity") is not None else None,
            "wind_speed_kmh": avg_wind,
            "rain_chance": avg_rain,
            "days": in_trip_days,
        }
    else:
        temp = curr.get("temp_c")
        humidity = curr.get("humidity")
        wind = curr.get("wind_kph")
        cond = curr.get("condition", {}).get("text")

        if end < today:
            note = "Trip dates are in the past. Forecast data is not available for past dates. Showing current conditions instead."
        else:
            note = "Trip dates are more than 14 days away. Forecasts only cover the next 14 days. Showing current conditions instead."

        return {
            "forecast_available": False,
            "forecast_note": note,
            "date_label": "Current conditions",
            "temp_display": f"{round(temp)}°C" if temp is not None else "Not available",
            "avg_high_c": None,
            "avg_low_c": None,
            "condition": cond or "Not available",
            "humidity": round(humidity) if humidity is not None else None,
            "wind_speed_kmh": round(wind) if wind is not None else None,
            "rain_chance": None,
            "days": in_trip_days,
        }


async def _fetch_weather(lat: float, lon: float, start: date, end: date) -> Optional[dict]:
    """Fetch weather with honest date checks, null guarding, and plain-language notes."""
    key = f"{lat:.3f},{lon:.3f}|{start}|{end}"
    cached = _weather_cache.get(key)
    if cached and time.time() - cached[0] < TTL:
        return cached[1]

    today = date.today()

    try:
        f = await _get("https://api.open-meteo.com/v1/forecast", {
            "latitude": lat,
            "longitude": lon,
            "timezone": "auto",
            "forecast_days": 16,
            "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m,precipitation",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,wind_speed_10m_max"
        })
        curr = f.get("current") or {}
        daily = f.get("daily") or {}
        times = daily.get("time") or []

        in_trip = [i for i, t in enumerate(times) if start.isoformat() <= t <= end.isoformat()]

        if in_trip:
            max_list = [daily["temperature_2m_max"][i] for i in in_trip if daily.get("temperature_2m_max") and daily["temperature_2m_max"][i] is not None]
            min_list = [daily["temperature_2m_min"][i] for i in in_trip if daily.get("temperature_2m_min") and daily["temperature_2m_min"][i] is not None]
            rain_list = [daily["precipitation_probability_max"][i] for i in in_trip if daily.get("precipitation_probability_max") and daily["precipitation_probability_max"][i] is not None]
            wind_list = [daily["wind_speed_10m_max"][i] for i in in_trip if daily.get("wind_speed_10m_max") and daily["wind_speed_10m_max"][i] is not None]
            codes_list = [daily["weather_code"][i] for i in in_trip if daily.get("weather_code") and daily["weather_code"][i] is not None]

            trip_days = []
            for i in in_trip:
                t_date = times[i]
                mx = daily["temperature_2m_max"][i] if daily.get("temperature_2m_max") else None
                mn = daily["temperature_2m_min"][i] if daily.get("temperature_2m_min") else None
                cd = daily["weather_code"][i] if daily.get("weather_code") else None
                rn = daily["precipitation_probability_max"][i] if daily.get("precipitation_probability_max") else None
                trip_days.append({
                    "date": t_date,
                    "max_c": round(mx, 1) if mx is not None else None,
                    "min_c": round(mn, 1) if mn is not None else None,
                    "condition": WMO.get(cd, "—") if cd is not None else "Not available",
                    "rain_chance": rn if rn is not None else None,
                })

            total_trip_days = (end - start).days + 1
            if len(in_trip) < total_trip_days:
                note = f"Showing forecast for days within the 16-day window ({len(in_trip)} of {total_trip_days} days). Future days will update as your trip approaches."
            else:
                note = None

            if max_list and min_list:
                avg_max = sum(max_list) / len(max_list)
                avg_min = sum(min_list) / len(min_list)
                avg_rain = round(sum(rain_list) / len(rain_list)) if rain_list else None
                avg_wind = round(sum(wind_list) / len(wind_list)) if wind_list else None
                top_code = Counter(codes_list).most_common(1)[0][0] if codes_list else None
                date_label = f"{times[in_trip[0]]} to {times[in_trip[-1]]}"

                data = {
                    "forecast_available": True,
                    "forecast_note": note,
                    "date_label": date_label,
                    "temp_display": f"{round(avg_min)}° / {round(avg_max)}°C avg",
                    "avg_high_c": round(avg_max),
                    "avg_low_c": round(avg_min),
                    "condition": WMO.get(top_code, "—") if top_code is not None else "Not available",
                    "humidity": round(curr.get("relative_humidity_2m")) if curr.get("relative_humidity_2m") is not None else None,
                    "wind_speed_kmh": avg_wind,
                    "rain_chance": avg_rain,
                    "days": trip_days,
                }
            else:
                data = {
                    "forecast_available": False,
                    "forecast_note": "The weather service did not return data for these dates yet.",
                    "date_label": "Not available",
                    "temp_display": "Not available",
                    "avg_high_c": None,
                    "avg_low_c": None,
                    "condition": "Not available",
                    "humidity": None,
                    "wind_speed_kmh": None,
                    "rain_chance": None,
                    "days": trip_days,
                }
        else:
            code = curr.get("weather_code")
            humidity = curr.get("relative_humidity_2m")
            wind = curr.get("wind_speed_10m")
            temp = curr.get("temperature_2m")

            if end < today:
                note = "Trip dates are in the past. Forecast data is not available for past dates. Showing current conditions instead."
            else:
                note = "Trip dates are more than 16 days away. Forecasts only cover the next 16 days. Showing current conditions instead."

            data = {
                "forecast_available": False,
                "forecast_note": note,
                "date_label": "Current conditions",
                "temp_display": f"{round(temp)}°C" if temp is not None else "Not available",
                "avg_high_c": None,
                "avg_low_c": None,
                "condition": WMO.get(code, "—") if code is not None else "Not available",
                "humidity": round(humidity) if humidity is not None else None,
                "wind_speed_kmh": round(wind) if wind is not None else None,
                "rain_chance": None,
                "days": [],
            }

        _weather_cache[key] = (time.time(), data)
        return data
    except Exception as exc:  # noqa: BLE001
        log.warning("Open-Meteo weather fetch failed for (%s, %s): %s; trying WeatherAPI fallback", lat, lon, exc)
        try:
            w_api = await _fetch_weatherapi(lat, lon, start, end)
            if w_api is not None:
                _weather_cache[key] = (time.time(), w_api)
                return w_api
        except Exception as fb_exc:  # noqa: BLE001
            log.warning("WeatherAPI fallback fetch also failed for (%s, %s): %s", lat, lon, fb_exc)

        return {
            "forecast_available": False,
            "forecast_note": "The weather service could not be reached. Try again in a moment.",
            "date_label": "Not available",
            "temp_display": "Not available",
            "avg_high_c": None,
            "avg_low_c": None,
            "condition": "Not available",
            "humidity": None,
            "wind_speed_kmh": None,
            "rain_chance": None,
            "days": [],
        }


async def _resolve_stops_background(
    destination: str,
    dest_loc: dict,
    start: date,
    end: date,
    candidates: list[str],
    cache_key: str,
    trip_id: Optional[int],
    cached_coordinates: Optional[dict[str, dict]] = None,
    itinerary_id: Optional[int] = None,
) -> None:
    """Background worker: progressively resolves candidate places, fetches weather, updates cache, and publishes event."""
    try:
        dest_lat, dest_lon = dest_loc["lat"], dest_loc["lon"]
        dest_name = dest_loc["name"]
        dest_country = dest_loc.get("country")

        resolved_locations = [dest_loc]
        unlocated_stops = []
        newly_resolved_coords: dict[str, dict] = {}

        # Validate candidates through LLM safety net
        validated_candidates = await validate_candidate_places_with_llm(destination, candidates)

        for candidate in validated_candidates:
            if candidate.lower() == destination.lower() or candidate.lower() == dest_name.lower():
                continue

            await asyncio.sleep(0.25)  # Space requests politely to prevent cloud IP throttling
            cand_geo, miss_reason = await _geocode_candidate_within_radius(
                name=candidate,
                dest_lat=dest_lat,
                dest_lon=dest_lon,
                dest_city=dest_name,
                dest_country=dest_country,
                max_dist_km=150.0,
                cached_coords=cached_coordinates,
            )

            if not cand_geo:
                unlocated_stops.append({"name": candidate, "reason": miss_reason or "Not found in the map database"})
                if cache_key in _cache:
                    entry = _cache[cache_key][1]
                    entry["unlocated_stops"] = list(unlocated_stops)
                    entry["pending_count"] = max(0, len(validated_candidates) - (len(resolved_locations) - 1) - len(unlocated_stops))
                continue

            # Record in newly resolved dict to persist to itinerary.days
            newly_resolved_coords[candidate.lower().strip()] = cand_geo
            if cand_geo.get("name"):
                newly_resolved_coords[cand_geo["name"].lower().strip()] = cand_geo

            # Only deduplicate against non-destination stops if within 50m
            is_dup = any(
                not existing.get("is_destination") and
                haversine_km(cand_geo["lat"], cand_geo["lon"], existing["lat"], existing["lon"]) < 0.05
                for existing in resolved_locations
            )
            if is_dup:
                continue

            resolved_locations.append({
                "name": cand_geo["name"],
                "label": cand_geo["display_name"],
                "country": cand_geo.get("country"),
                "admin": cand_geo.get("admin"),
                "lat": cand_geo["lat"],
                "lon": cand_geo["lon"],
                "distance_km": cand_geo["distance_km"],
                "is_destination": False,
                "is_region": False,
                "is_approximate": cand_geo.get("is_approximate", False),
                "weather": None,  # to be filled concurrently
            })

            # Progressive update to cache so active pollers receive stops immediately
            if cache_key in _cache:
                entry = _cache[cache_key][1]
                entry["locations"] = list(resolved_locations)
                entry["unlocated_stops"] = list(unlocated_stops)
                entry["pending_count"] = max(0, len(validated_candidates) - (len(resolved_locations) - 1) - len(unlocated_stops))
                entry["status_message"] = f"Locating stops on map... ({len(resolved_locations)-1} found)"

            if len(resolved_locations) >= 16:
                break

        # Persist newly resolved coordinates into itinerary.days in database so subsequent requests make 0 external calls
        if itinerary_id and newly_resolved_coords:
            _persist_itinerary_coordinates(itinerary_id, newly_resolved_coords)

        # Concurrently fetch weather for all resolved stops
        stop_locs = [loc for loc in resolved_locations if not loc.get("is_destination")]
        if stop_locs:
            weather_tasks = [_fetch_weather(loc["lat"], loc["lon"], start, end) for loc in stop_locs]
            weather_results = await asyncio.gather(*weather_tasks, return_exceptions=True)
            for loc, w_res in zip(stop_locs, weather_results):
                loc["weather"] = w_res if isinstance(w_res, dict) else None

        # Update cache with complete results
        if cache_key in _cache:
            existing_out = _cache[cache_key][1]
            existing_out["locations"] = resolved_locations
            existing_out["unlocated_stops"] = unlocated_stops
            existing_out["is_resolving"] = False
            existing_out["pending_count"] = 0
            existing_out["status_message"] = None
            _cache[cache_key] = (time.time(), existing_out)
        else:
            final_out = {
                "destination": destination,
                "location": dest_loc,
                "locations": resolved_locations,
                "unlocated_stops": unlocated_stops,
                "is_resolving": False,
                "pending_count": 0,
                "status_message": None,
                "attribution": "Geocoding: © OpenStreetMap contributors (Nominatim), Photon & Open-Meteo. Weather: Open-Meteo.com & WeatherAPI.com.",
                "errors": []
            }
            _cache[cache_key] = (time.time(), final_out)

        # Notify via WebSocket
        if trip_id:
            publish(trip_id, {"type": "research_updated"})

    except Exception as exc:
        log.exception("Background stop resolution failed for %s: %s", destination, exc)
    finally:
        _active_background_tasks.discard(cache_key)


async def overview(
    destination: str,
    start: date,
    end: date,
    itinerary_days: Optional[list[dict]] = None,
    itinerary_version: Optional[int] = None,
    trip_id: Optional[int] = None,
    raw_plan: Optional[str] = None,
    cached_coordinates: Optional[dict[str, dict]] = None,
    itinerary_id: Optional[int] = None,
) -> dict[str, Any]:
    # Content hash ensures regenerated itineraries invalidate cached overview immediately
    itinerary_hash = hashlib.md5(json.dumps(itinerary_days or [], sort_keys=True).encode()).hexdigest()[:8]
    key = f"{destination.lower()}|{start}|{end}|v{itinerary_version or 0}|{itinerary_hash}"
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < TTL:
        # If still resolving, return cached partial state
        return hit[1]

    out: dict[str, Any] = {
        "destination": destination,
        "location": None,
        "locations": [],
        "unlocated_stops": [],
        "weather": None,
        "is_resolving": False,
        "pending_count": 0,
        "status_message": None,
        "attribution": "Geocoding: © OpenStreetMap contributors (Nominatim), Photon & Open-Meteo. Weather: Open-Meteo.com & WeatherAPI.com.",
        "errors": []
    }

    geo = await geocode_place(destination)
    if not geo:
        out["errors"].append(f"Couldn't find “{destination}” on the map. Try a more specific place name.")
        return out

    dest_lat, dest_lon = geo["lat"], geo["lon"]
    dest_name = geo["name"]
    dest_country = geo.get("country")
    geo_type = geo.get("type", "")

    is_region = (
        geo_type in ("country", "state", "province")
        or (dest_country and dest_country.lower() == dest_name.lower())
    )

    dest_label = f"{dest_name} (region overview)" if is_region else f"{dest_name} (Destination)"
    dest_loc = {
        "name": dest_name,
        "label": dest_label,
        "country": dest_country,
        "admin": geo.get("admin"),
        "lat": dest_lat,
        "lon": dest_lon,
        "is_destination": True,
        "is_region": is_region,
        "is_approximate": False,
        "distance_km": 0.0,
        "weather": None,
    }
    out["location"] = dest_loc

    dest_weather = await _fetch_weather(dest_lat, dest_lon, start, end)
    dest_loc["weather"] = dest_weather

    if dest_weather and dest_weather.get("days"):
        out["weather"] = {
            "days": dest_weather["days"],
            "covers_trip": dest_weather["forecast_available"],
            "note": dest_weather["forecast_note"],
        }
    else:
        out["weather"] = {
            "days": [],
            "covers_trip": False,
            "note": dest_weather.get("forecast_note") if dest_weather else "Weather information currently unavailable.",
        }

    candidates = extract_locations_from_itinerary(
        itinerary_days or [],
        max_candidates=25,
        destination=destination,
        raw_plan=raw_plan,
    )
    
    # Check if all candidate stops are already cached (in itinerary.days or in-memory cache)
    resolved_locations = [dest_loc]
    unlocated_stops = []
    uncached_candidates = []

    for candidate in candidates:
        if candidate.lower() == destination.lower() or candidate.lower() == dest_name.lower():
            continue
        c_key = f"{candidate.lower().strip()}|{dest_name.lower().strip()}|{dest_lat:.2f},{dest_lon:.2f}"

        # 1. Check persistent itinerary.days cached_coordinates first (0 network calls)
        cand_geo = None
        cand_norm = candidate.lower().strip()
        if cached_coordinates and cand_norm in cached_coordinates:
            cand_geo = cached_coordinates[cand_norm]
        elif cached_coordinates:
            for v in _generate_name_variants(candidate):
                v_norm = v.lower().strip()
                if v_norm in cached_coordinates:
                    cand_geo = cached_coordinates[v_norm]
                    break

        if cand_geo and isinstance(cand_geo, dict) and "lat" in cand_geo and "lon" in cand_geo:
            _geocode_cache[c_key] = cand_geo
            resolved_locations.append({
                "name": cand_geo.get("name") or candidate,
                "label": cand_geo.get("display_name") or cand_geo.get("label") or candidate,
                "country": cand_geo.get("country"),
                "admin": cand_geo.get("admin"),
                "lat": cand_geo["lat"],
                "lon": cand_geo["lon"],
                "distance_km": cand_geo.get("distance_km", 0.0),
                "is_destination": False,
                "is_region": False,
                "is_approximate": cand_geo.get("is_approximate", False),
                "weather": None,
            })
        elif c_key in _geocode_cache and _geocode_cache[c_key]:
            cand_geo = _geocode_cache[c_key]
            resolved_locations.append({
                "name": cand_geo["name"],
                "label": cand_geo["display_name"],
                "country": cand_geo.get("country"),
                "admin": cand_geo.get("admin"),
                "lat": cand_geo["lat"],
                "lon": cand_geo["lon"],
                "distance_km": cand_geo["distance_km"],
                "is_destination": False,
                "is_region": False,
                "is_approximate": cand_geo.get("is_approximate", False),
                "weather": None,
            })
        elif c_key in _geocode_miss_cache:
            ts, reason = _geocode_miss_cache[c_key]
            if time.time() - ts < MISS_TTL:
                unlocated_stops.append({"name": candidate, "reason": reason})
        else:
            uncached_candidates.append(candidate)

    if not uncached_candidates:
        # All candidates already resolved and cached! Fetch weather for stops and return immediately (0 external geocoding calls)
        stop_locs = [loc for loc in resolved_locations if not loc.get("is_destination")]
        if stop_locs:
            weather_tasks = [_fetch_weather(loc["lat"], loc["lon"], start, end) for loc in stop_locs]
            weather_results = await asyncio.gather(*weather_tasks, return_exceptions=True)
            for loc, w_res in zip(stop_locs, weather_results):
                loc["weather"] = w_res if isinstance(w_res, dict) else None

        out["locations"] = resolved_locations
        out["unlocated_stops"] = unlocated_stops
        out["is_resolving"] = False
        _cache[key] = (time.time(), out)
        return out

    # Progressive loading: return destination and already-resolved stops immediately (< 3s)
    out["locations"] = resolved_locations
    out["unlocated_stops"] = unlocated_stops
    out["is_resolving"] = True
    out["pending_count"] = len(uncached_candidates)
    out["status_message"] = f"Locating {len(uncached_candidates)} itinerary stops on map..."
    _cache[key] = (time.time(), out)

    # Launch background task if not already running
    if key not in _active_background_tasks:
        _active_background_tasks.add(key)
        asyncio.create_task(
            _resolve_stops_background(
                destination=destination,
                dest_loc=dest_loc,
                start=start,
                end=end,
                candidates=candidates,
                cache_key=key,
                trip_id=trip_id,
                cached_coordinates=cached_coordinates,
                itinerary_id=itinerary_id,
            )
        )

    return out

    return out
