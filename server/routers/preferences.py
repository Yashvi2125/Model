from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from server.db import get_db
from server.models import Preference, PreferenceSuggestion, utcnow
from server.schemas import PreferenceIn, PreferenceOut, PreferencesOverview, SuggestionOut
from server.services import preferences as prefs
from server.services.access import TripAccess, trip_access
from server.services.realtime import publish

router = APIRouter(prefix="/api/trips/{trip_id}/preferences", tags=["preferences"])


def _out(user, pref, me_id: int) -> PreferenceOut:
    base = dict(user_id=user.id, user_name=user.name, is_me=user.id == me_id, missing=prefs.missing_fields(pref))
    if not pref:
        return PreferenceOut(**base)
    return PreferenceOut(**base, destination=pref.destination, start_date=pref.start_date, end_date=pref.end_date,
                         trip_days=pref.trip_days, interests=pref.interests or [], budget_min=pref.budget_min,
                         budget_max=pref.budget_max, accommodation=pref.accommodation, dietary=pref.dietary,
                         restrictions=pref.restrictions, notes=pref.notes, sources=pref.sources or {},
                         updated_at=pref.updated_at)


def _overview(db: Session, a: TripAccess) -> PreferencesOverview:
    rows = prefs.member_prefs(db, a.trip.id)
    mine = db.scalars(select(PreferenceSuggestion).where(
        PreferenceSuggestion.trip_id == a.trip.id, PreferenceSuggestion.user_id == a.user.id,
        PreferenceSuggestion.status == "pending").order_by(PreferenceSuggestion.id.desc())).all()
    total = db.scalar(select(func.count()).select_from(PreferenceSuggestion).where(
        PreferenceSuggestion.trip_id == a.trip.id, PreferenceSuggestion.status == "pending")) or 0
    missing = []
    if not a.trip.destination and not any(p and p.destination for _, p in rows):
        missing.append("destination")
    return PreferencesOverview(members=[_out(u, p, a.user.id) for u, p in rows],
                               my_suggestions=[SuggestionOut.model_validate(s) for s in mine],
                               pending_suggestions_total=total, trip_missing=missing)


@router.get("", response_model=PreferencesOverview)
def get_preferences(a: TripAccess = Depends(trip_access), db: Session = Depends(get_db)):
    return _overview(db, a)


@router.put("/me", response_model=PreferencesOverview)
def save_my_preferences(body: PreferenceIn, a: TripAccess = Depends(trip_access), db: Session = Depends(get_db)):
    pref = prefs.get_or_create(db, a.trip.id, a.user.id)
    sources = dict(pref.sources or {})
    for key, value in body.model_dump(exclude_unset=True).items():
        if key == "interests" and value is None:
            value = []
        setattr(pref, key, value)
        if value in (None, "", []):
            sources.pop(key, None)
        else:
            sources[key] = "direct"  # anything saved through this form is the member's own words
    pref.sources = sources
    pref.updated_at = utcnow()
    db.commit()
    publish(a.trip.id, {"type": "preferences_updated"})
    return _overview(db, a)


def _own_pending(db: Session, a: TripAccess, sid: int) -> PreferenceSuggestion:
    s = db.get(PreferenceSuggestion, sid)
    if not s or s.trip_id != a.trip.id or s.user_id != a.user.id:
        raise HTTPException(404, "Suggestion not found.")  # only the person it is about can review it
    if s.status != "pending":
        raise HTTPException(409, "This suggestion was already reviewed.")
    return s


@router.post("/suggestions/{sid}/accept", response_model=PreferencesOverview)
def accept(sid: int, a: TripAccess = Depends(trip_access), db: Session = Depends(get_db)):
    s = _own_pending(db, a, sid)
    pref = prefs.get_or_create(db, a.trip.id, a.user.id)
    prefs.apply_fields(pref, prefs.coerce_for_model(s.data), "ai")
    s.status, s.resolved_at = "accepted", utcnow()
    db.commit()
    publish(a.trip.id, {"type": "preferences_updated"})
    return _overview(db, a)


@router.post("/suggestions/{sid}/dismiss", response_model=PreferencesOverview)
def dismiss(sid: int, a: TripAccess = Depends(trip_access), db: Session = Depends(get_db)):
    s = _own_pending(db, a, sid)
    s.status, s.resolved_at = "dismissed", utcnow()
    db.commit()
    publish(a.trip.id, {"type": "preferences_updated"})
    return _overview(db, a)
