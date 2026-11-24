"""Preference helpers: merging, missing-info detection and AI suggestions (never auto-applied)."""
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from server.models import Preference, PreferenceSuggestion, Trip, TripMember, User, utcnow

FIELDS = ["destination", "start_date", "end_date", "trip_days", "interests", "budget_min", "budget_max",
          "accommodation", "dietary", "restrictions", "notes"]
EMPTY = (None, "", [])


def get_or_create(db: Session, trip_id: int, user_id: int) -> Preference:
    pref = db.scalar(select(Preference).where(Preference.trip_id == trip_id, Preference.user_id == user_id))
    if not pref:
        pref = Preference(trip_id=trip_id, user_id=user_id, interests=[], sources={})
        db.add(pref)
        db.flush()
    return pref


def apply_fields(pref: Preference, data: dict[str, Any], source: str) -> None:
    sources = dict(pref.sources or {})
    for key, value in data.items():
        if key not in FIELDS or value in EMPTY:
            continue
        setattr(pref, key, value)
        sources[key] = source
    pref.sources = sources
    pref.updated_at = utcnow()


def seed_from_trip(db: Session, trip: Trip, user_id: int) -> None:
    """The organiser's own answers in the create-trip form become their direct preferences."""
    pref = get_or_create(db, trip.id, user_id)
    data = {
        "destination": trip.destination, "start_date": trip.start_date, "end_date": trip.end_date,
        "interests": list(trip.interests or []), "budget_max": trip.budget_per_person,
        "accommodation": trip.accommodation_pref, "dietary": trip.dietary,
        "restrictions": " · ".join(x for x in [trip.accessibility, trip.constraints] if x) or None,
        "notes": trip.notes,
    }
    if data["budget_max"] is None and trip.budget_total:
        data["budget_max"] = round(float(trip.budget_total) / trip.travelers_count, 2)
    apply_fields(pref, data, "direct")


def missing_fields(pref: Optional[Preference]) -> list[str]:
    if pref is None:
        return ["interests", "budget", "dates", "accommodation"]
    out = []
    if not pref.interests:
        out.append("interests")
    if pref.budget_min is None and pref.budget_max is None:
        out.append("budget")
    if not ((pref.start_date and pref.end_date) or pref.trip_days):
        out.append("dates")
    if not pref.accommodation:
        out.append("accommodation")
    return out


def fields_from_extracted(ex, travelers: int) -> dict[str, Any]:
    data: dict[str, Any] = {}
    if ex.destination:
        data["destination"] = ex.destination.strip()[:120]
    if ex.trip_days:
        data["trip_days"] = ex.trip_days
    if ex.start_date:
        data["start_date"] = ex.start_date.isoformat()
    if ex.end_date:
        data["end_date"] = ex.end_date.isoformat()
    if ex.budget_per_person:
        data["budget_max"] = ex.budget_per_person
    elif ex.budget_total and travelers:
        data["budget_max"] = round(ex.budget_total / travelers, 2)
    if ex.interests:
        data["interests"] = ex.interests[:12]
    for k in ("accommodation", "dietary", "restrictions", "notes"):
        v = getattr(ex, k)
        if v:
            data[k] = v.strip()[:500]
    if ex.currency and ex.currency.upper() != "INR" and "budget_max" in data:
        data["notes"] = (data.get("notes", "") + f" (budget stated in {ex.currency.upper()})").strip()
    if getattr(ex, "provider", None):
        data["_provider"] = ex.provider
    if getattr(ex, "model", None):
        data["_model"] = ex.model
    return data


def create_suggestion(db: Session, trip_id: int, user_id: int, message_id: Optional[int], data: dict, confidence: float):
    if not data:
        return None
    pending = db.scalars(select(PreferenceSuggestion).where(
        PreferenceSuggestion.trip_id == trip_id, PreferenceSuggestion.user_id == user_id,
        PreferenceSuggestion.status == "pending")).all()
    for dup in pending:  # compare in Python: PostgreSQL has no equality operator for JSON columns
        if dup.data == data:
            return dup
    s = PreferenceSuggestion(trip_id=trip_id, user_id=user_id, message_id=message_id, data=data, confidence=confidence)
    db.add(s)
    db.flush()
    return s


def coerce_for_model(data: dict[str, Any]) -> dict[str, Any]:
    from datetime import date
    out = dict(data)
    for k in ("start_date", "end_date"):
        if isinstance(out.get(k), str):
            try:
                out[k] = date.fromisoformat(out[k])
            except ValueError:
                out.pop(k)
    return out


def member_prefs(db: Session, trip_id: int) -> list[tuple[User, Optional[Preference]]]:
    members = db.scalars(select(TripMember).where(TripMember.trip_id == trip_id).order_by(TripMember.joined_at)).all()
    prefs = {p.user_id: p for p in db.scalars(select(Preference).where(Preference.trip_id == trip_id))}
    return [(m.user, prefs.get(m.user_id)) for m in members]
