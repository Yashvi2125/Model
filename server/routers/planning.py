import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from server import runtime
from server.ai.client import AIError, ai_status, friendly_error
from server.db import get_db
from server.models import Itinerary, User
from server.schemas import GenerateIn, ItineraryListItem, ItineraryOut
from pydantic import BaseModel


class DaySwapIn(BaseModel):
    instruction: str
from server.security import current_user
from server.services import itinerary_service as svc
from server.services.access import TripAccess, trip_access
from server.services.budget import compute_budget

log = logging.getLogger("tripmate.planning")
router = APIRouter(tags=["planning"])


@router.get("/api/ai/status")
def status(_: User = Depends(current_user)):
    s = ai_status()
    return {**s, "ready": s["gemini_configured"],
            "notes": [] if s["gemini_configured"] and s["tavily_configured"] else
            ([] if s["gemini_configured"] else ["GEMINI_API_KEY is missing: AI chat, conflict suggestions and itineraries are disabled."])
            + ([] if s["tavily_configured"] else ["TAVILY_API_KEY is missing: itineraries are generated without live web research."])}


@router.get("/api/trips/{trip_id}/itinerary", response_model=Optional[ItineraryOut])
def latest(a: TripAccess = Depends(trip_access), db: Session = Depends(get_db)):
    return db.scalar(select(Itinerary).where(Itinerary.trip_id == a.trip.id).order_by(Itinerary.version.desc()))


@router.get("/api/trips/{trip_id}/itineraries", response_model=list[ItineraryListItem])
def history(a: TripAccess = Depends(trip_access), db: Session = Depends(get_db)):
    return db.scalars(select(Itinerary).where(Itinerary.trip_id == a.trip.id).order_by(Itinerary.version.desc())).all()


@router.get("/api/trips/{trip_id}/itineraries/{version}", response_model=ItineraryOut)
def by_version(version: int, a: TripAccess = Depends(trip_access), db: Session = Depends(get_db)):
    it = db.scalar(select(Itinerary).where(Itinerary.trip_id == a.trip.id, Itinerary.version == version))
    if not it:
        raise HTTPException(404, "That itinerary version doesn't exist.")
    return it


@router.post("/api/trips/{trip_id}/itinerary/generate", response_model=ItineraryOut, status_code=202)
def generate(body: GenerateIn, a: TripAccess = Depends(trip_access), db: Session = Depends(get_db)):
    if not ai_status()["gemini_configured"]:
        raise HTTPException(503, "The AI assistant isn't set up yet. Add GEMINI_API_KEY to the .env file and restart the backend.")
    try:
        it = svc.start_run(db, a.trip, a.user.id, (body.instructions or "").strip() or None)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))
    runtime.spawn(svc.run_generation(it.id))  # background: the request returns immediately
    return it


def _latest_success(db: Session, trip_id: int) -> Optional[Itinerary]:
    return db.scalar(select(Itinerary).where(Itinerary.trip_id == trip_id, Itinerary.status == "succeeded")
                     .order_by(Itinerary.version.desc()))


@router.post("/api/trips/{trip_id}/itinerary/days/{day_number}/swap", response_model=ItineraryOut)
async def swap_day(
    trip_id: int,
    day_number: int,
    body: DaySwapIn,
    a: TripAccess = Depends(trip_access),
    db: Session = Depends(get_db),
):
    it = _latest_success(db, a.trip.id)
    if not it:
        raise HTTPException(404, "No generated itinerary found to edit.")

    days_data = it.days if isinstance(it.days, dict) else {}
    days_list = list(days_data.get("days", []))
    target_idx = -1
    for idx, d in enumerate(days_list):
        if d.get("day") == day_number:
            target_idx = idx
            break

    if target_idx == -1:
        raise HTTPException(404, f"Day {day_number} not found in this itinerary.")

    from server.services.context import trip_context
    from server.services import preferences as prefs_svc
    from server.services.itinerary_parser import extract_structured_places_from_content
    from server.ai.local_llm import swap_itinerary_day

    pref_rows = prefs_svc.member_prefs(db, a.trip.id)
    ctx = trip_context(a.trip, pref_rows)

    updated_day, provider = await swap_itinerary_day(days_list[target_idx], body.instruction.strip(), ctx)

    day_places = []
    for s in updated_day.get("sections", []):
        day_places.extend(extract_structured_places_from_content(s.get("content", "")))
    updated_day["places"] = day_places
    updated_day["_provider"] = provider

    days_list[target_idx] = updated_day
    days_data["days"] = days_list
    it.days = dict(days_data)

    # Reconstruct plan_markdown
    md_parts = [days_data.get("overview", "")]
    for d in days_list:
        md_parts.append(f"\n## Day {d.get('day')}: {d.get('title', '')}\n")
        if d.get("intro"):
            md_parts.append(f"{d['intro']}\n")
        for sec in d.get("sections", []):
            md_parts.append(f"### {sec.get('period', '').title()}\n{sec.get('content', '')}\n")
    if days_data.get("tail"):
        md_parts.append(f"\n{days_data['tail']}\n")
    it.plan_markdown = "\n".join(md_parts).strip()

    db.commit()
    db.refresh(it)
    return it


def _budget_payload(db: Session, a: TripAccess) -> dict:
    t = a.trip
    it = _latest_success(db, t.id)
    running = db.scalar(select(Itinerary.id).where(Itinerary.trip_id == t.id, Itinerary.status == "running")) is not None
    data = compute_budget(it.budget_items if it else None, t.travelers_count, t.start_date, t.end_date,
                          float(t.budget_total) if t.budget_total else None,
                          float(t.budget_per_person) if t.budget_per_person else None)
    return {**data, "currency": t.currency, "flexibility": t.budget_flexibility,
            "itinerary_version": it.version if it else None, "budget_error": it.budget_error if it else None,
            "generating": running, "members_joined": len(t.members)}


@router.get("/api/trips/{trip_id}/budget")
def budget(a: TripAccess = Depends(trip_access), db: Session = Depends(get_db)):
    return _budget_payload(db, a)


@router.post("/api/trips/{trip_id}/budget/estimate")
async def re_estimate(a: TripAccess = Depends(trip_access), db: Session = Depends(get_db)):
    it = _latest_success(db, a.trip.id)
    if not it:
        raise HTTPException(400, "Generate an itinerary first. The budget is calculated from its stated costs.")
    if not ai_status()["gemini_configured"]:
        raise HTTPException(503, "The AI assistant isn't set up yet. Add GEMINI_API_KEY to the .env file.")
    await svc.estimate_budget(it.id)
    db.expire_all()
    return _budget_payload(db, a)
