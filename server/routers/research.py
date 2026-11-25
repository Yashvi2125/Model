from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from server.ai.client import ai_status
from server.db import get_db
from server.models import Itinerary
from server.services import preferences as prefs
from server.services import research as research_service
from server.services.access import TripAccess, trip_access
from server.services.itinerary_service import resolve_destination

router = APIRouter(tags=["research"])


@router.get("/api/trips/{trip_id}/research")
async def research(a: TripAccess = Depends(trip_access), db: Session = Depends(get_db)):
    t = a.trip
    dest = resolve_destination(t, prefs.member_prefs(db, t.id))
    it = db.scalar(select(Itinerary).where(Itinerary.trip_id == t.id, Itinerary.status == "succeeded")
                   .order_by(Itinerary.version.desc()))
    notes = {
        "research_markdown": it.research_markdown if it else None,
        "sources": (it.days or {}).get("sources", []) if it else [],
        "search_used": it.search_used if it else None,
        "itinerary_version": it.version if it else None,
        "tavily_configured": ai_status()["tavily_configured"],
    }
    if not dest:
        return {**notes, "destination": None, "location": None, "locations": [], "weather": None, "errors": [],
                "unavailable_reason": "No destination has been chosen yet. Add one to the trip or to a member's preferences."}
    itinerary_days = (it.days or {}).get("days", []) if it else []
    cached_coordinates = (it.days or {}).get("cached_coordinates", {}) if it else {}
    data = await research_service.overview(
        dest,
        t.start_date,
        t.end_date,
        itinerary_days=itinerary_days,
        itinerary_version=it.version if it else 0,
        trip_id=t.id,
        raw_plan=it.plan_markdown if it else None,
        cached_coordinates=cached_coordinates,
        itinerary_id=it.id if it else None,
    )
    if it and data.get("locations"):
        coords = {}
        for loc in data["locations"]:
            if not loc.get("is_destination") and loc.get("lat") is not None and loc.get("lon") is not None:
                coords[loc["name"].lower().strip()] = {
                    "name": loc["name"],
                    "label": loc.get("label") or loc["name"],
                    "lat": loc["lat"],
                    "lon": loc["lon"],
                    "country": loc.get("country"),
                    "admin": loc.get("admin"),
                    "distance_km": loc.get("distance_km", 0.0),
                    "is_approximate": loc.get("is_approximate", False),
                }
        if coords:
            days_dict = dict(it.days or {})
            existing = dict(days_dict.get("cached_coordinates") or {})
            changed = False
            for k, v in coords.items():
                if k not in existing or existing[k] != v:
                    existing[k] = v
                    changed = True
            if changed:
                days_dict["cached_coordinates"] = existing
                it.days = days_dict
                db.commit()
    return {**notes, **data}
