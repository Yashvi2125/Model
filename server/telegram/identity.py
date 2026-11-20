"""Identity bridging and group binding for Telegram users and trips."""
import logging
import secrets
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from server.models import Trip, TripMember, User, utcnow
from server.security import hash_password

log = logging.getLogger("tripmate.telegram.identity")


def get_or_create_telegram_user(
    db: Session, tg_user_id: int, full_name: str, username: Optional[str] = None
) -> User:
    """Finds or creates a backend User row corresponding to a Telegram user.
    Prioritises linked web accounts (User.telegram_user_id == tg_user_id).
    Falls back to synthetic user (tg_<id>@telegram.user).
    """
    # 1. Check for linked web account
    linked_user = db.scalar(
        select(User).where(User.telegram_user_id == tg_user_id, ~User.email.endswith("@telegram.user"))
    )
    if linked_user:
        if username and linked_user.telegram_username != username:
            linked_user.telegram_username = username
            db.commit()
        return linked_user

    # 2. Check for synthetic user
    email = f"tg_{tg_user_id}@telegram.user"
    user = db.scalar(select(User).where(User.email == email))
    if not user:
        display_name = (full_name or "").strip() or (username or "").strip() or f"User {tg_user_id}"
        user = User(
            email=email,
            name=display_name[:100],
            password_hash=hash_password(secrets.token_urlsafe(24)),
            telegram_username=username,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    elif full_name and user.name != full_name:
        user.name = full_name[:100]
        if username:
            user.telegram_username = username
        db.commit()
    return user


def get_trip_by_chat_id(db: Session, chat_id: int) -> Optional[Trip]:
    """Retrieves the active Trip bound to this Telegram group chat."""
    return db.scalar(select(Trip).where(Trip.telegram_group_chat_id == chat_id))


def get_trip_by_code(db: Session, code: str) -> Optional[Trip]:
    """Retrieves a Trip by its code (normalised)."""
    norm = "".join(ch for ch in code.upper() if ch.isalnum())
    return db.scalar(select(Trip).where((Trip.code == norm) | (Trip.trip_code == norm)))


def bind_trip_to_chat(db: Session, trip: Trip, chat_id: int) -> None:
    """Binds this trip to a Telegram group chat. Clears any previous trip bound to this chat."""
    prev_trips = db.scalars(
        select(Trip).where(Trip.telegram_group_chat_id == chat_id, Trip.id != trip.id)
    ).all()
    for prev in prev_trips:
        prev.telegram_group_chat_id = None
    trip.telegram_group_chat_id = chat_id
    db.commit()


def ensure_trip_member(
    db: Session,
    trip_id: int,
    user_id: int,
    tg_user_id: Optional[int] = None,
    tg_username: Optional[str] = None,
    role: str = "member",
) -> TripMember:
    """Ensures a user is registered as a member of the given trip."""
    member = db.scalar(
        select(TripMember).where(TripMember.trip_id == trip_id, TripMember.user_id == user_id)
    )
    if not member:
        member = TripMember(
            trip_id=trip_id,
            user_id=user_id,
            role=role,
            telegram_user_id=tg_user_id,
            telegram_username=tg_username,
            channel_origin="telegram" if tg_user_id else "web",
            last_accessed_at=utcnow(),
        )
        db.add(member)
        db.commit()
        db.refresh(member)
    else:
        changed = False
        if tg_user_id and not member.telegram_user_id:
            member.telegram_user_id = tg_user_id
            changed = True
        if tg_username and member.telegram_username != tg_username:
            member.telegram_username = tg_username
            changed = True
        if changed:
            db.commit()
    return member
