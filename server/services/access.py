"""Trip authorisation helpers. Non-members get 404 so trip IDs cannot be probed."""
from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from server.db import get_db
from server.models import Trip, TripMember, User
from server.security import current_user

NOT_FOUND = "Trip not found, or you are not a member of it."


class TripAccess:
    def __init__(self, trip: Trip, member: TripMember, user: User):
        self.trip, self.member, self.user = trip, member, user

    @property
    def is_owner(self) -> bool:
        return self.member.role == "owner"

    def require_owner(self) -> None:
        if not self.is_owner:
            raise HTTPException(403, "Only the trip organiser can do this.")


def trip_access(trip_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> TripAccess:
    row = db.execute(
        select(Trip, TripMember).join(TripMember, TripMember.trip_id == Trip.id)
        .where(Trip.id == trip_id, TripMember.user_id == user.id)
    ).first()
    if not row:
        raise HTTPException(404, NOT_FOUND)
    return TripAccess(row[0], row[1], user)


def get_member_ids(db: Session, trip_id: int) -> list[int]:
    return list(db.scalars(select(TripMember.user_id).where(TripMember.trip_id == trip_id)))
