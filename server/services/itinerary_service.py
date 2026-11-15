"""Itinerary generation: builds the planning prompt, runs the existing agent team in the background, stores results."""
import asyncio
import logging
from collections import Counter
from datetime import timedelta
from typing import Optional

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from server.ai import agents
from server.ai.client import AIError, ai_status, friendly_error
from server.ai.workflow import generate_plan
from server.db import SessionLocal
from server.models import Conflict, Itinerary, Trip, as_utc, utcnow
from server.services import messages as msgs
from server.services import preferences as prefs
from server.services.context import trip_context
from server.services.itinerary_parser import parse_itinerary
from server.services.realtime import publish

log = logging.getLogger("tripmate.itinerary")
STALE_AFTER = timedelta(minutes=12)


def resolve_destination(trip: Trip, rows) -> Optional[str]:
    if trip.destination:
        return trip.destination
    names = [p.destination.strip() for _, p in rows if p and p.destination]
    return Counter(n.title() for n in names).most_common(1)[0][0] if names else None


def build_prompt(db: Session, trip: Trip, instructions: Optional[str]) -> tuple[str, str]:
    rows = prefs.member_prefs(db, trip.id)
    dest = resolve_destination(trip, rows)
    if not dest:
        raise ValueError("Choose a destination first: add one in the trip details or in a member's preferences.")
    days = (trip.end_date - trip.start_date).days + 1
    decided = db.scalars(select(Conflict).where(Conflict.trip_id == trip.id, Conflict.status == "accepted")).all()
    interests = list(dict.fromkeys(i for _, p in rows if p for i in (p.interests or [])))
    prompt = (
        f"Plan a {days}-day trip to {dest} for {trip.travelers_count} people, {trip.start_date:%d %b %Y} to {trip.end_date:%d %b %Y}.\n"
        f"{trip_context(trip, rows)}\n"
        + ("Group decisions already agreed:\n" + "\n".join(f"- {c.title}: {c.suggestion}" for c in decided) + "\n" if decided else "")
        + (f"Extra instructions from the group: {instructions}\n" if instructions else "")
        + "Balance every member's interests across the days and respect dietary needs and restrictions.\n"
          f"Format: a 2-3 sentence summary, then for each day a heading '## Day N: <theme>' with '**Morning**', '**Afternoon**' and "
          f"'**Evening**' bullet lists, with estimated costs in {trip.currency}. End with a short '## Stay & transport tips' section."
    )
    return prompt, f"{dest} travel guide top attractions restaurants hotels " + " ".join(interests[:4])


def start_run(db: Session, trip: Trip, user_id: int, instructions: Optional[str]) -> Itinerary:
    build_prompt(db, trip, instructions)  # validate early so the user gets a clear 400
    latest = db.scalar(select(Itinerary).where(Itinerary.trip_id == trip.id, Itinerary.status == "running")
                       .order_by(Itinerary.id.desc()))
    if latest and utcnow() - as_utc(latest.created_at) < STALE_AFTER:
        raise RuntimeError("An itinerary is already being generated for this trip.")
    version = (db.scalar(select(func.max(Itinerary.version)).where(Itinerary.trip_id == trip.id)) or 0) + 1
    it = Itinerary(trip_id=trip.id, version=version, status="running", instructions=instructions,
                   created_by_id=user_id, days={})
    db.add(it)
    db.commit()
    db.refresh(it)
    return it


def mark_stale_runs_failed() -> None:
    with SessionLocal() as db:
        db.execute(update(Itinerary).where(Itinerary.status == "running").values(
            status="failed", error="The server restarted while this itinerary was being generated. Please generate it again.",
            completed_at=utcnow()))
        db.commit()


def _begin(itinerary_id: int):
    with SessionLocal() as db:
        it = db.get(Itinerary, itinerary_id)
        trip = db.get(Trip, it.trip_id)
        prompt, query = build_prompt(db, trip, it.instructions)
        return trip.id, trip.currency, trip.travelers_count, (trip.end_date - trip.start_date).days + 1, prompt, query


def _finish_ok(itinerary_id: int, res) -> int:
    import config.settings as s
    with SessionLocal() as db:
        it = db.get(Itinerary, itinerary_id)
        it.status, it.plan_markdown, it.research_markdown = "succeeded", res.plan, res.research
        it.days, it.transcript, it.search_used = parse_itinerary(res.plan), res.transcript, res.search_used
        it.model, it.completed_at = s.GEMINI_MODEL, utcnow()
        db.get(Trip, it.trip_id).status = "itinerary_ready"
        db.commit()
        note = f"Itinerary v{it.version} is ready." + ("" if res.search_used else " Live web research wasn't available, so it's based on the AI's general knowledge.")
        msgs.post(db, it.trip_id, "system", note, None, {"itinerary_id": it.id})
        return it.version


def _finish_fail(itinerary_id: int, message: str) -> None:
    with SessionLocal() as db:
        it = db.get(Itinerary, itinerary_id)
        it.status, it.error, it.completed_at = "failed", message, utcnow()
        db.commit()
        msgs.post(db, it.trip_id, "system", f"Itinerary generation failed: {message}", None, {"itinerary_id": it.id, "error": True})


def _save_budget(itinerary_id: int, items: Optional[list], error: Optional[str]) -> None:
    with SessionLocal() as db:
        it = db.get(Itinerary, itinerary_id)
        it.budget_items, it.budget_error = items, error
        db.commit()


async def estimate_budget(itinerary_id: int) -> None:
    def load():
        with SessionLocal() as db:
            it = db.get(Itinerary, itinerary_id)
            t = db.get(Trip, it.trip_id)
            return it.plan_markdown or "", t.currency, t.travelers_count, (t.end_date - t.start_date).days + 1
    plan, cur, n, days = await asyncio.to_thread(load)
    try:
        items = await agents.extract_budget_items(plan, cur, n, days)
        await asyncio.to_thread(_save_budget, itinerary_id, items, None if items else
                                "The plan doesn't state any costs, so there's nothing to total yet. Regenerate it and ask for estimated costs.")
    except Exception as exc:  # noqa: BLE001
        await asyncio.to_thread(_save_budget, itinerary_id, None, friendly_error(exc).user_message)


async def run_generation(itinerary_id: int) -> None:
    trip_id = None
    try:
        trip_id, _, _, _, prompt, query = await asyncio.to_thread(_begin, itinerary_id)
        publish(trip_id, {"type": "itinerary_updated"})
        publish(trip_id, {"type": "ai_status", "state": "thinking", "label": "Planning your itinerary…"})
        res = await generate_plan(prompt, query)
        await asyncio.to_thread(_finish_ok, itinerary_id, res)
        publish(trip_id, {"type": "itinerary_updated"})
        await estimate_budget(itinerary_id)
    except Exception as exc:  # noqa: BLE001
        err = friendly_error(exc)
        log.exception("Itinerary generation failed") if not isinstance(exc, AIError) else None
        await asyncio.to_thread(_finish_fail, itinerary_id, err.user_message)
    finally:
        if trip_id:
            publish(trip_id, {"type": "itinerary_updated"})
            publish(trip_id, {"type": "ai_status", "state": "idle"})
