import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from server.db import get_db
from server.models import ChecklistItem, Trip, TripMember, User, utcnow
from server.schemas import (JoinIn, JoiningIn, MemberOut, TripCreate, TripDetail, TripPreview, TripSummary, TripUpdate)
from server.security import current_user, rate_limit
from server.services import messages as msgs
from server.services import preferences as prefs
from server.services.access import NOT_FOUND, TripAccess, trip_access
from server.services.realtime import publish

log = logging.getLogger("tripmate.trips")

router = APIRouter(prefix="/api/trips", tags=["trips"])

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I
DEFAULT_CHECKLIST = ["Confirm travel dates with everyone", "Finalise the itinerary", "Review accommodation options",
                     "Review transport options", "Check required documents (ID, tickets, permits)",
                     "Prepare a packing list", "Confirm group preferences and dietary needs"]


def normalise_code(code: str) -> str:
    return "".join(ch for ch in code.upper() if ch.isalnum())


def new_code(db: Session) -> str:
    for _ in range(20):
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
        if not db.scalar(select(Trip.id).where(Trip.code == code)):
            return code
    raise HTTPException(500, "Couldn't generate a trip code. Please try again.")


def _summary(trip: Trip, member: TripMember, count: int) -> TripSummary:
    s = TripSummary.model_validate(trip)
    return s.model_copy(update={"member_count": count, "my_role": member.role, "last_accessed_at": member.last_accessed_at})


def _detail(db: Session, trip: Trip, member: TripMember) -> TripDetail:
    members = db.scalars(select(TripMember).where(TripMember.trip_id == trip.id).order_by(TripMember.joined_at)).all()
    skip = {"members", "member_count", "my_role", "last_accessed_at"}
    base = {k: getattr(trip, k) for k in TripDetail.model_fields if k not in skip}
    return TripDetail(**base, member_count=len(members), my_role=member.role, last_accessed_at=member.last_accessed_at,
                      members=[MemberOut(user_id=m.user_id, name=m.user.name, role=m.role,
                                         channel_origin=getattr(m, "channel_origin", "web") or "web",
                                         telegram_username=getattr(m, "telegram_username", None),
                                         joined_at=m.joined_at)
                               for m in members])


@router.post("", response_model=TripDetail, status_code=201)
def create_trip(body: TripCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    data = body.model_dump()
    code = new_code(db)
    trip = Trip(**data, code=code, trip_code=code, owner_id=user.id)
    db.add(trip)
    db.flush()
    member = TripMember(trip_id=trip.id, user_id=user.id, role="owner", last_accessed_at=utcnow())
    db.add(member)
    prefs.seed_from_trip(db, trip, user.id)
    for i, text in enumerate(DEFAULT_CHECKLIST):
        db.add(ChecklistItem(trip_id=trip.id, text=text, position=i))
    db.commit()
    msgs.post(db, trip.id, "system", f"{user.name} created the trip. Share the code {trip.code} to invite friends — "
                                     "and mention @ai in chat to talk to MileMates AI.")
    return _detail(db, trip, member)


@router.get("", response_model=list[TripSummary])
def list_trips(user: User = Depends(current_user), db: Session = Depends(get_db)):
    counts = select(TripMember.trip_id, func.count().label("n")).group_by(TripMember.trip_id).subquery()
    rows = db.execute(
        select(Trip, TripMember, counts.c.n).join(TripMember, TripMember.trip_id == Trip.id)
        .join(counts, counts.c.trip_id == Trip.id).where(TripMember.user_id == user.id).order_by(Trip.start_date)).all()
    return [_summary(t, m, n) for t, m, n in rows]


@router.get("/preview/{code}", response_model=TripPreview)
def preview(code: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    rate_limit(f"code:{user.id}", 30, 60)
    norm = normalise_code(code)
    trip = db.scalar(select(Trip).where((Trip.code == norm) | (Trip.trip_code == norm)))
    if not trip:
        raise HTTPException(404, "That trip code doesn't match any trip. Check it and try again.")
    ids = [m.user_id for m in trip.members]
    return TripPreview(code=trip.code, name=trip.name, destination=trip.destination, start_date=trip.start_date,
                       end_date=trip.end_date, member_count=len(ids), owner_name=trip.owner.name,
                       already_member=user.id in ids, trip_id=trip.id if user.id in ids else None)


@router.post("/join", response_model=TripPreview)
def join(body: JoinIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    rate_limit(f"code:{user.id}", 30, 60)
    norm = normalise_code(body.code)
    trip = db.scalar(select(Trip).where((Trip.code == norm) | (Trip.trip_code == norm)))
    if not trip:
        raise HTTPException(404, "That trip code doesn't match any trip. Check it and try again.")
    ids = [m.user_id for m in trip.members]
    if user.id not in ids:
        if not trip.is_joinable:
            raise HTTPException(403, "This trip isn't accepting new members right now. Ask the organiser.")
        if len(ids) >= 50:
            raise HTTPException(403, "This trip is full.")
        db.add(TripMember(trip_id=trip.id, user_id=user.id, role="member", last_accessed_at=utcnow()))
        db.commit()
        msgs.post(db, trip.id, "system", f"{user.name} joined the trip.")
        ids.append(user.id)
    return TripPreview(code=trip.code, name=trip.name, destination=trip.destination, start_date=trip.start_date,
                       end_date=trip.end_date, member_count=len(ids), owner_name=trip.owner.name,
                       already_member=True, trip_id=trip.id)


@router.get("/{trip_id}", response_model=TripDetail)
def get_trip(a: TripAccess = Depends(trip_access), db: Session = Depends(get_db)):
    a.member.last_accessed_at = utcnow()
    db.commit()
    return _detail(db, a.trip, a.member)


@router.patch("/{trip_id}", response_model=TripDetail)
def update_trip(body: TripUpdate, a: TripAccess = Depends(trip_access), db: Session = Depends(get_db)):
    a.require_owner()
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(a.trip, k, v)
    if a.trip.end_date < a.trip.start_date:
        raise HTTPException(422, "Return date can't be before the departure date.")
    db.commit()
    return _detail(db, a.trip, a.member)


@router.delete("/{trip_id}", status_code=204)
def delete_trip(a: TripAccess = Depends(trip_access), db: Session = Depends(get_db)):
    a.require_owner()
    trip_id = a.trip.id
    if a.trip.telegram_group_chat_id:
        log.info("Deleting trip %s, clearing Telegram group chat binding %s", trip_id, a.trip.telegram_group_chat_id)
    db.delete(a.trip)
    db.commit()
    publish(trip_id, {"type": "trip_deleted", "trip_id": trip_id})


@router.patch("/{trip_id}/joining", response_model=TripDetail)
def set_joining(body: JoiningIn, a: TripAccess = Depends(trip_access), db: Session = Depends(get_db)):
    a.require_owner()
    a.trip.is_joinable = body.is_joinable
    db.commit()
    return _detail(db, a.trip, a.member)


@router.post("/{trip_id}/invite/regenerate", response_model=TripDetail)
def regenerate_code(a: TripAccess = Depends(trip_access), db: Session = Depends(get_db)):
    a.require_owner()
    a.trip.code = new_code(db)
    db.commit()
    return _detail(db, a.trip, a.member)


@router.post("/{trip_id}/leave", status_code=204)
def leave(a: TripAccess = Depends(trip_access), db: Session = Depends(get_db)):
    if a.is_owner:
        raise HTTPException(400, "The organiser can't leave the trip. Delete it instead.")
    db.delete(a.member)
    db.commit()
    msgs.post(db, a.trip.id, "system", f"{a.user.name} left the trip.")


@router.delete("/{trip_id}/members/{user_id}", status_code=204)
def remove_member(user_id: int, a: TripAccess = Depends(trip_access), db: Session = Depends(get_db)):
    a.require_owner()
    if user_id == a.user.id:
        raise HTTPException(400, "You can't remove yourself as organiser.")
    m = db.scalar(select(TripMember).where(TripMember.trip_id == a.trip.id, TripMember.user_id == user_id))
    if not m:
        raise HTTPException(404, "That person isn't a member of this trip.")
    name = m.user.name
    db.delete(m)
    db.commit()
    msgs.post(db, a.trip.id, "system", f"{name} was removed from the trip.")
