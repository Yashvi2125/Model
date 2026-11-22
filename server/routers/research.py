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
    data = await research_service.overview(
        dest,
        t.start_date,
        t.end_date,
        itinerary_days=itinerary_days,
        itinerary_version=it.version if it else 0,
        trip_id=t.id,
    )
    return {**notes, **data}
