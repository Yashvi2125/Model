import pytest
import time
from datetime import date
from unittest.mock import AsyncMock
import httpx

from server.services import research
from tests.web.conftest import make_trip


def test_haversine_distance():
    # Tokyo (35.6895, 139.6917) to Kamakura (35.3108, 139.5470) ~ 44 km
    d = research.haversine_km(35.6895, 139.6917, 35.3108, 139.5470)
    assert 40 < d < 50

    # Distance > 150 km rejected
    d_far = research.haversine_km(35.6895, 139.6917, 40.7128, -74.0060)
    assert d_far > 10000


def test_extract_locations_from_itinerary_cap():
    days = [
        {
            "day": i + 1,
            "title": f"Day {i + 1}: Visit Location_{i + 1}",
            "sections": [
                {"period": "morning", "content": f"Visit Stop_{i * 2 + 1} for sightseeing."},
                {"period": "afternoon", "content": f"Explore Stop_{i * 2 + 2} area."},
            ],
        }
        for i in range(20)
    ]
    locs = research.extract_locations_from_itinerary(days)
    assert len(locs) <= 25


def test_score_nominatim_ambiguous_same_named_candidates():
    # "Goa" with Genoa (Italy), Goa (Philippines), and Goa (India state)
    cand_italy = {"name": "Genoa", "display_name": "Genoa, Liguria, Italy", "importance": 0.85, "type": "city"}
    cand_phil = {"name": "Goa", "display_name": "Goa, Camarines Sur, Philippines", "importance": 0.40, "type": "administrative"}
    cand_india = {"name": "Goa", "display_name": "Goa, India", "importance": 0.65, "type": "administrative"}

    # Scoring "Goa, India"
    s_india_hint = research._score_nominatim_candidate("Goa, India", cand_india)
    s_italy_hint = research._score_nominatim_candidate("Goa, India", cand_italy)
    assert s_india_hint > s_italy_hint

    # Scoring "Goa": exact name match gives Goa strong priority over fuzzy Genoa
    s_goa = research._score_nominatim_candidate("Goa", cand_india)
    s_genoa = research._score_nominatim_candidate("Goa", cand_italy)
    assert s_goa > s_genoa


@pytest.mark.asyncio
async def test_weather_with_null_values_ignores_nulls_cleanly(monkeypatch):
    """A missing/null day on Open-Meteo edge run must never break the card or produce zeros."""
    start = date(2026, 12, 3)
    end = date(2026, 12, 8)

    async def mock_get(url, params):
        return {
            "current": {
                "temperature_2m": 10.0,
                "relative_humidity_2m": 70,
                "weather_code": 0,
                "wind_speed_10m": 5.0,
            },
            "daily": {
                "time": ["2026-12-03", "2026-12-04", "2026-12-05", "2026-12-06", "2026-12-07"],
                "temperature_2m_max": [16.0, 17.0, 18.0, 17.0, None],  # Edge of run has None
                "temperature_2m_min": [6.0, 7.0, 8.0, 6.0, None],       # Edge of run has None
                "precipitation_probability_max": [0, 5, 10, 5, 0],
                "wind_speed_10m_max": [8, 10, 12, 10, None],
                "weather_code": [0, 1, 2, 1, None],
            },
        }

    monkeypatch.setattr(research, "_get", mock_get)
    w = await research._fetch_weather(30.455, 78.071, start, end)
    assert w is not None
    assert w["forecast_available"] is True
    # Average max across [16, 17, 18, 17] = 17.0, min across [6, 7, 8, 6] = 6.75 (round 7)
    assert w["avg_high_c"] == 17
    assert w["avg_low_c"] == 7
    assert "avg" in w["temp_display"]
    # Check that day 5 with null is captured without breaking
    assert len(w["days"]) == 5
    assert w["days"][4]["max_c"] is None
    assert w["days"][4]["min_c"] is None
    assert w["days"][4]["condition"] == "Not available"


@pytest.mark.asyncio
async def test_weather_outside_16_day_window_shows_no_fake_rain(monkeypatch):
    start = date(2027, 8, 1)
    end = date(2027, 8, 8)

    async def mock_get(url, params):
        return {
            "current": {
                "temperature_2m": 22.0,
                "relative_humidity_2m": 65,
                "weather_code": 1,
                "wind_speed_10m": 12.0,
            },
            "daily": {
                "time": ["2026-11-20", "2026-11-21"],
                "temperature_2m_max": [20.0, 21.0],
                "temperature_2m_min": [12.0, 13.0],
                "precipitation_probability_max": [10, 15],
                "wind_speed_10m_max": [10, 12],
                "weather_code": [0, 0],
            },
        }

    monkeypatch.setattr(research, "_get", mock_get)
    w = await research._fetch_weather(35.6895, 139.6917, start, end)
    assert w is not None
    assert w["forecast_available"] is False
    assert "16 days" in w["forecast_note"]
    assert w["rain_chance"] is None  # No fake numbers!
    assert "22°C" in w["temp_display"]


@pytest.mark.asyncio
async def test_weather_fallback_to_weatherapi_when_open_meteo_fails(monkeypatch):
    """When Open-Meteo returns 429 or fails, the service falls back to WeatherAPI without crashing."""
    research._weather_cache.clear()
    start = date(2026, 12, 3)
    end = date(2026, 12, 8)

    async def mock_open_meteo_fail(url, params):
        raise RuntimeError("429 Too Many Requests")

    async def mock_weatherapi_success(lat, lon, s, e):
        return {
            "forecast_available": True,
            "forecast_note": None,
            "date_label": "2026-12-03 to 2026-12-08",
            "temp_display": "7° / 18°C avg",
            "avg_high_c": 18,
            "avg_low_c": 7,
            "condition": "Partly cloudy",
            "humidity": 55,
            "wind_speed_kmh": 10,
            "rain_chance": 15,
            "days": [
                {"date": "2026-12-03", "max_c": 18.0, "min_c": 7.0, "condition": "Partly cloudy", "rain_chance": 15}
            ],
        }

    monkeypatch.setattr(research, "_get", mock_open_meteo_fail)
    monkeypatch.setattr(research, "_fetch_weatherapi", mock_weatherapi_success)

    w = await research._fetch_weather(30.455, 78.071, start, end)
    assert w is not None
    assert w["forecast_available"] is True
    assert w["condition"] == "Partly cloudy"
    assert w["avg_high_c"] == 18


@pytest.mark.asyncio
async def test_unreachable_services_degrade_gracefully(monkeypatch):
    async def fail_get(url, params, headers=None):
        raise RuntimeError("Service down")

    monkeypatch.setattr(research, "_get", fail_get)
    res = await research.overview("NonExistentOrOffline", date(2026, 12, 1), date(2026, 12, 5))
    assert res["location"] is None
    assert res["locations"] == []
    assert len(res["errors"]) > 0


def test_research_endpoint_returns_structured_overview(user_a, monkeypatch):
    t = make_trip(user_a, destination="Varanasi")
    tid = t["id"]

    async def mock_overview(dest, start, end, itinerary_days=None, **kwargs):
        return {
            "destination": dest,
            "location": {"name": "Varanasi", "country": "India", "lat": 25.3356, "lon": 83.0076, "is_destination": True},
            "locations": [
                {
                    "name": "Varanasi",
                    "label": "Varanasi (Destination)",
                    "country": "India",
                    "lat": 25.3356,
                    "lon": 83.0076,
                    "is_destination": True,
                    "distance_km": 0.0,
                    "weather": {
                        "date_label": "2026-11-22 to 2026-11-26",
                        "temp_display": "14° / 28°C avg",
                        "avg_high_c": 28,
                        "avg_low_c": 14,
                        "condition": "Clear sky",
                        "humidity": 65,
                        "wind_speed_kmh": 8,
                        "rain_chance": 0,
                        "forecast_available": True,
                        "forecast_note": None,
                        "days": [],
                    },
                }
            ],
            "unlocated_stops": [],
            "weather": {"days": [], "covers_trip": True, "note": None},
            "attribution": "OpenStreetMap & Open-Meteo",
            "errors": [],
        }

    monkeypatch.setattr(research, "overview", mock_overview)
    r = user_a.get(f"/api/trips/{tid}/research").json()
    assert r["destination"] == "Varanasi"
    assert len(r["locations"]) == 1
    assert r["locations"][0]["country"] == "India"
    assert r["locations"][0]["weather"]["temp_display"] == "14° / 28°C avg"


@pytest.mark.asyncio
async def test_landmark_found_only_via_bounded_search(monkeypatch):
    """Test landmark successfully located via bounded viewbox search."""
    research._geocode_cache.clear()
    research._geocode_miss_cache.clear()
    monkeypatch.setattr(research, "_throttle_nominatim", AsyncMock())

    async def mock_get(url, params, headers=None):
        if "viewbox" in params:
            return [{
                "name": "Law Garden",
                "lat": "23.0230",
                "lon": "72.5580",
                "importance": 0.5,
                "address": {"country": "India", "state": "Gujarat"},
            }]
        return []

    monkeypatch.setattr(research, "_get", mock_get)
    res, reason = await research._geocode_candidate_within_radius(
        name="Law Garden",
        dest_lat=23.0225,
        dest_lon=72.5714,
        dest_city="Ahmedabad",
        dest_country="India",
    )
    assert res is not None
    assert res["name"] == "Law Garden"
    assert res["distance_km"] < 5.0
    assert reason is None


@pytest.mark.asyncio
async def test_landmark_found_only_via_photon(monkeypatch):
    """Test landmark resolved via Photon when Nominatim misses spelling variant."""
    research._geocode_cache.clear()
    research._geocode_miss_cache.clear()
    monkeypatch.setattr(research, "_throttle_nominatim", AsyncMock())

    async def mock_nominatim_get(url, params, headers=None):
        return []

    async def mock_photon(query, lat, lon):
        if "sidi" in query.lower():
            return [{
                "name": "Sidi Saiyad Mosque",
                "country": "India",
                "admin": "Gujarat",
                "lat": 23.0270,
                "lon": 72.5810,
                "type": "place",
                "display_name": "Sidi Saiyad Mosque",
            }]
        return []

    monkeypatch.setattr(research, "_get", mock_nominatim_get)
    monkeypatch.setattr(research, "_query_photon", mock_photon)

    res, reason = await research._geocode_candidate_within_radius(
        name="Sidi Saiyyed Mosque",
        dest_lat=23.0225,
        dest_lon=72.5714,
        dest_city="Ahmedabad",
        dest_country="India",
    )
    assert res is not None
    assert res["name"] == "Sidi Saiyyed Mosque"
    assert res["lat"] == 23.0270
    assert reason is None


@pytest.mark.asyncio
async def test_landmark_found_only_after_dropping_generic_word(monkeypatch):
    """Test landmark resolved after stripping generic word (e.g. Emporium -> Gujari)."""
    research._geocode_cache.clear()
    research._geocode_miss_cache.clear()
    monkeypatch.setattr(research, "_throttle_nominatim", AsyncMock())

    async def mock_get(url, params, headers=None):
        q = params.get("q", "")
        # Bare "Gujari Emporium" fails, but stripped "Gujari" succeeds
        if "emporium" not in q.lower() and "gujari" in q.lower():
            return [{
                "name": "Gujari Bazar",
                "lat": "23.0180",
                "lon": "72.5790",
                "importance": 0.45,
                "address": {"country": "India", "state": "Gujarat"},
            }]
        return []

    monkeypatch.setattr(research, "_get", mock_get)
    res, reason = await research._geocode_candidate_within_radius(
        name="Gujari Emporium",
        dest_lat=23.0225,
        dest_lon=72.5714,
        dest_city="Ahmedabad",
        dest_country="India",
    )
    assert res is not None
    assert res["name"] == "Gujari Emporium"
    assert res["lat"] == 23.0180
    assert reason is None


@pytest.mark.asyncio
async def test_landmark_resolved_via_gemini_approximate_fallback(monkeypatch):
    """Test well-known landmark resolved via Gemini fallback tagged as approximate location."""
    research._geocode_cache.clear()
    research._geocode_miss_cache.clear()
    monkeypatch.setattr(research, "_throttle_nominatim", AsyncMock())

    async def mock_empty_get(url, params, headers=None):
        return []

    async def mock_empty_photon(query, lat, lon):
        return []

    async def mock_gemini(name, city, country):
        if "toran" in name.lower():
            return {
                "name": "Toran Dining Hall",
                "lat": 23.0337,
                "lon": 72.5645,
                "is_approximate": True,
                "display_name": "Toran Dining Hall (approximate location)",
            }
        return None

    monkeypatch.setattr(research, "_get", mock_empty_get)
    monkeypatch.setattr(research, "_query_photon", mock_empty_photon)
    monkeypatch.setattr(research, "_approximate_location_with_gemini", mock_gemini)

    res, reason = await research._geocode_candidate_within_radius(
        name="Toran Dining Hall",
        dest_lat=23.0225,
        dest_lon=72.5714,
        dest_city="Ahmedabad",
        dest_country="India",
    )
    assert res is not None
    assert res["name"] == "Toran Dining Hall"
    assert res["is_approximate"] is True
    assert res["lat"] == 23.0337
    assert reason is None


@pytest.mark.asyncio
async def test_landmark_not_found_anywhere_returns_proper_miss_reason(monkeypatch):
    """Test unfound stop returns proper miss reason in unlocated stops."""
    research._geocode_cache.clear()
    research._geocode_miss_cache.clear()
    monkeypatch.setattr(research, "_throttle_nominatim", AsyncMock())

    async def mock_empty_get(url, params, headers=None):
        return []

    async def mock_empty_photon(query, lat, lon):
        return []

    async def mock_gemini(name, city, country):
        return None

    monkeypatch.setattr(research, "_get", mock_empty_get)
    monkeypatch.setattr(research, "_query_photon", mock_empty_photon)
    monkeypatch.setattr(research, "_approximate_location_with_gemini", mock_gemini)

    res, reason = await research._geocode_candidate_within_radius(
        name="Completely NonExistent Stop 999",
        dest_lat=23.0225,
        dest_lon=72.5714,
        dest_city="Ahmedabad",
        dest_country="India",
    )
    assert res is None
    assert reason == "Not found in the map database"


@pytest.mark.asyncio
async def test_unhandled_geocoder_error_or_timeout(monkeypatch):
    """Test graceful error handling when external geocoding times out."""
    research._geocode_cache.clear()
    research._geocode_miss_cache.clear()
    monkeypatch.setattr(research, "_throttle_nominatim", AsyncMock())

    async def mock_error_get(url, params, headers=None):
        raise httpx.TimeoutException("Connection timed out")

    async def mock_error_photon(query, lat, lon):
        raise httpx.TimeoutException("Photon timed out")

    async def mock_error_gemini(name, city, country):
        raise RuntimeError("AI model timeout")

    monkeypatch.setattr(research, "_get", mock_error_get)
    monkeypatch.setattr(research, "_query_photon", mock_error_photon)
    monkeypatch.setattr(research, "_approximate_location_with_gemini", mock_error_gemini)

    res, reason = await research._geocode_candidate_within_radius(
        name="Timeout Landmark",
        dest_lat=23.0225,
        dest_lon=72.5714,
        dest_city="Ahmedabad",
        dest_country="India",
    )
    assert res is None
    assert reason == "Lookup timed out"


def test_extract_locations_uses_structured_places_first():
    """Verify structured places on day objects take precedence over text scraping."""
    days = [
        {
            "day": 1,
            "title": "Day 1: Thematic Title Never Used As Place",
            "sections": [{"period": "morning", "content": "Text with **Old Scraped Stop**"}],
            "places": [
                {"name": "Eiffel Tower", "area": "7th Arrondissement", "kind": "attraction"},
                {"name": "Louvre Museum", "area": "1st Arrondissement", "kind": "attraction"}
            ]
        }
    ]
    extracted = research.extract_locations_from_itinerary(days)
    assert extracted == ["Eiffel Tower", "Louvre Museum"]
    assert "Thematic Title Never Used As Place" not in extracted
    assert "Old Scraped Stop" not in extracted


def test_fallback_extractor_rejects_headings_determiners_and_clauses():
    """Verify fallback extractor rejects day headings, determiners, and clause fragments."""
    days = [
        {
            "day": 1,
            "title": "Day 1: History & Architecture",
            "sections": [
                {
                    "period": "morning",
                    "content": (
                        "* **Sabarmati Ashram:** Start at the ashram.\n"
                        "* **Sidi Saiyyed Mosque:** Visit this 16th-century mosque famous for its intricate stone-carved window.\n"
                        "* **Lunch at Agashiye:** Authentic rooftop dining.\n"
                        "* **Dinner at Manek Chowk:** Bustling night market."
                    )
                }
            ]
        },
        {
            "day": 2,
            "title": "Day 2: Leisure & Recreation",
            "sections": [
                {
                    "period": "morning",
                    "content": "* **Adalaj Stepwell:** Magnificent five-story stepwell.\n* **Dinner:** Local snacks."
                }
            ]
        }
    ]
    extracted = research.extract_locations_from_itinerary(days)
    # Proper places must be extracted cleanly without meal prefixes
    assert "Sabarmati Ashram" in extracted
    assert "Sidi Saiyyed Mosque" in extracted
    assert "Agashiye" in extracted
    assert "Manek Chowk" in extracted
    assert "Adalaj Stepwell" in extracted

    # Headings and fragments MUST be rejected
    assert "History" not in extracted
    assert "Architecture" not in extracted
    assert "Leisure" not in extracted
    assert "Recreation" not in extracted
    assert "this 16th-century mosque famous" not in extracted
    assert "Dinner" not in extracted


@pytest.mark.asyncio
async def test_validate_candidate_places_with_llm(monkeypatch):
    """Verify batched LLM safety net validates genuine places and discards non-places."""
    research._llm_validation_cache.clear()

    async def mock_llm_json(*args, **kwargs):
        return {
            "valid_places": ["Sabarmati Ashram", "Atal Pedestrian Bridge"]
        }

    monkeypatch.setattr("server.ai.client.llm_json", mock_llm_json)
    candidates = ["Sabarmati Ashram", "Atal Pedestrian Bridge", "Local Food", "Shopping"]
    validated = await research.validate_candidate_places_with_llm("Ahmedabad", candidates)
    assert validated == ["Sabarmati Ashram", "Atal Pedestrian Bridge"]
    assert "Local Food" not in validated


@pytest.mark.asyncio
async def test_overview_progressive_loading_initial_response(monkeypatch):
    """Verify fast initial response returns destination and is_resolving=True when stops are pending."""
    research.invalidate_cache()
    monkeypatch.setattr(research, "_throttle_nominatim", AsyncMock())

    async def mock_geocode(name):
        return {"name": "Ahmedabad", "country": "India", "lat": 23.0225, "lon": 72.5714, "type": "city"}

    async def mock_weather(lat, lon, start, end):
        return {"temp_display": "25°C", "condition": "Clear", "forecast_available": True, "days": []}

    monkeypatch.setattr(research, "geocode_place", mock_geocode)
    monkeypatch.setattr(research, "_fetch_weather", mock_weather)

    days = [{
        "day": 1,
        "title": "Day 1",
        "sections": [{"period": "morning", "content": "* **Sabarmati Ashram:** Gandhi home."}]
    }]

    out = await research.overview("Ahmedabad", date(2026, 11, 28), date(2026, 11, 30), itinerary_days=days)
    assert out["destination"] == "Ahmedabad"
    assert out["location"]["name"] == "Ahmedabad"
    assert out["is_resolving"] is True
    assert out["pending_count"] > 0
    assert "Locating" in out["status_message"]


@pytest.mark.asyncio
async def test_cloud_geocoding_fallback_when_nominatim_blocked_and_caching(monkeypatch):
    """Verifies that when Nominatim returns HTTP 429 or 403 (cloud IP block on Render),
    fallback geocoders (Photon & Open-Meteo) resolve all stops and cache them in itinerary.days.
    """
    research.invalidate_cache()
    # Reset circuit breaker
    research._nominatim_blocked_until = 0.0

    nominatim_calls = []
    photon_calls = []

    async def mock_get(url, params=None, headers=None):
        if "nominatim.openstreetmap.org" in url:
            nominatim_calls.append(url)
            # Simulate Cloud IP Block: HTTP 429 Too Many Requests
            resp = httpx.Response(429, request=httpx.Request("GET", url))
            raise httpx.HTTPStatusError("429 Too Many Requests", request=resp.request, response=resp)
        elif "open-meteo.com/v1/forecast" in url:
            return {"current": {"temperature_2m": 26, "weather_code": 1}, "daily": {"time": []}}
        return {}

    async def mock_query_photon(query, lat, lon):
        photon_calls.append(query)
        # Mock Photon returning coordinates near Ahmedabad (23.0225, 72.5714)
        if "sabarmati" in query.lower():
            return [{
                "name": "Sabarmati Ashram",
                "country": "India",
                "admin": "Gujarat",
                "lat": 23.0605,
                "lon": 72.5804,
                "type": "landmark",
                "display_name": "Sabarmati Ashram, Ahmedabad",
            }]
        elif "kankaria" in query.lower():
            return [{
                "name": "Kankaria Lake",
                "country": "India",
                "admin": "Gujarat",
                "lat": 23.0064,
                "lon": 72.6026,
                "type": "landmark",
                "display_name": "Kankaria Lake, Ahmedabad",
            }]
        return []

    async def mock_geocode_place(name):
        return {"name": "Ahmedabad", "country": "India", "lat": 23.0225, "lon": 72.5714, "type": "city"}

    monkeypatch.setattr(research, "_get", mock_get)
    monkeypatch.setattr(research, "_query_photon", mock_query_photon)
    monkeypatch.setattr(research, "geocode_place", mock_geocode_place)
    monkeypatch.setattr(research, "_throttle_nominatim", AsyncMock(return_value=True))

    dest_lat, dest_lon = 23.0225, 72.5714

    # 1. Direct call to _geocode_candidate_within_radius when Nominatim is 429 blocked
    geo, reason = await research._geocode_candidate_within_radius(
        name="Sabarmati Ashram",
        dest_lat=dest_lat,
        dest_lon=dest_lon,
        dest_city="Ahmedabad",
        dest_country="India",
        max_dist_km=150.0,
    )
    assert geo is not None, f"Expected fallback resolution, got reason: {reason}"
    assert geo["name"] == "Sabarmati Ashram"
    assert round(geo["lat"], 2) == 23.06
    assert len(nominatim_calls) > 0  # Nominatim was attempted
    assert len(photon_calls) > 0     # Photon fallback succeeded
    assert research._nominatim_blocked_until > time.time()  # Circuit breaker opened

    # 2. Verify cached_coords in itinerary.days avoids any external calls (0 network requests)
    cached = {
        "kankaria lake": {
            "name": "Kankaria Lake",
            "display_name": "Kankaria Lake, Ahmedabad",
            "lat": 23.0064,
            "lon": 72.6026,
            "distance_km": 3.5,
            "country": "India",
            "admin": "Gujarat",
        }
    }
    photon_calls_before = len(photon_calls)
    nominatim_calls_before = len(nominatim_calls)

    cached_geo, _ = await research._geocode_candidate_within_radius(
        name="Kankaria Lake",
        dest_lat=dest_lat,
        dest_lon=dest_lon,
        dest_city="Ahmedabad",
        dest_country="India",
        max_dist_km=150.0,
        cached_coords=cached,
    )
    assert cached_geo is not None
    assert cached_geo["name"] == "Kankaria Lake"
    # Zero external geocoding calls made because it was resolved from cached_coords
    assert len(photon_calls) == photon_calls_before
    assert len(nominatim_calls) == nominatim_calls_before

    # 3. Test overview() with full cached_coordinates resolves immediately with is_resolving=False
    days = [{
        "day": 1,
        "title": "Day 1",
        "sections": [{"period": "morning", "content": "* **Kankaria Lake:** Lake walk."}],
        "places": ["Kankaria Lake"]
    }]
    out = await research.overview(
        "Ahmedabad",
        date(2026, 11, 28),
        date(2026, 11, 30),
        itinerary_days=days,
        cached_coordinates=cached,
    )
    assert out["is_resolving"] is False
    assert any(loc["name"] == "Kankaria Lake" for loc in out["locations"])



