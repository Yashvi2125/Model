"""SQLAlchemy models. The Alembic migration in alembic/versions mirrors this file."""
from datetime import date, datetime, timezone
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from server.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


TS = sa.DateTime(timezone=True)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(sa.String(100))
    email: Mapped[str] = mapped_column(sa.String(254), unique=True, index=True)  # stored lowercase
    password_hash: Mapped[str] = mapped_column(sa.String(255))
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(sa.String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(TS)
    last_used_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    user_agent: Mapped[Optional[str]] = mapped_column(sa.String(255))


class Trip(Base):
    __tablename__ = "trips"
    __table_args__ = (
        sa.CheckConstraint("end_date >= start_date", name="ck_trips_dates"),
        sa.CheckConstraint("travelers_count >= 1", name="ck_trips_travelers"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(sa.String(12), unique=True, index=True)
    name: Mapped[str] = mapped_column(sa.String(120))
    destination: Mapped[Optional[str]] = mapped_column(sa.String(120))
    destination_undecided: Mapped[bool] = mapped_column(default=False)
    start_date: Mapped[date] = mapped_column(sa.Date)
    end_date: Mapped[date] = mapped_column(sa.Date)
    travelers_count: Mapped[int] = mapped_column(default=1)
    budget_total: Mapped[Optional[float]] = mapped_column(sa.Numeric(14, 2))
    budget_per_person: Mapped[Optional[float]] = mapped_column(sa.Numeric(14, 2))
    currency: Mapped[str] = mapped_column(sa.String(3), default="INR")
    budget_flexibility: Mapped[str] = mapped_column(sa.String(20), default="flexible")
    interests: Mapped[list] = mapped_column(sa.JSON, default=list)
    accommodation_pref: Mapped[Optional[str]] = mapped_column(sa.String(200))
    dietary: Mapped[Optional[str]] = mapped_column(sa.Text)
    accessibility: Mapped[Optional[str]] = mapped_column(sa.Text)
    constraints: Mapped[Optional[str]] = mapped_column(sa.Text)
    notes: Mapped[Optional[str]] = mapped_column(sa.Text)
    status: Mapped[str] = mapped_column(sa.String(20), default="planning")
    is_joinable: Mapped[bool] = mapped_column(default=True)
    owner_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)

    owner: Mapped[User] = relationship()
    members: Mapped[list["TripMember"]] = relationship(back_populates="trip", cascade="all, delete-orphan")


class TripMember(Base):
    __tablename__ = "trip_members"
    __table_args__ = (sa.UniqueConstraint("trip_id", "user_id", name="uq_trip_member"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    trip_id: Mapped[int] = mapped_column(sa.ForeignKey("trips.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(sa.String(12), default="member")  # owner | member
    joined_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    last_accessed_at: Mapped[Optional[datetime]] = mapped_column(TS)

    trip: Mapped[Trip] = relationship(back_populates="members")
    user: Mapped[User] = relationship()


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (sa.Index("ix_messages_trip_id_id", "trip_id", "id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    trip_id: Mapped[int] = mapped_column(sa.ForeignKey("trips.id", ondelete="CASCADE"))
    sender_id: Mapped[Optional[int]] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(sa.String(10), default="user")  # user | ai | system
    content: Mapped[str] = mapped_column(sa.Text)
    meta: Mapped[dict] = mapped_column(sa.JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)

    sender: Mapped[Optional[User]] = relationship()


class Preference(Base):
    __tablename__ = "preferences"
    __table_args__ = (sa.UniqueConstraint("trip_id", "user_id", name="uq_preference_member"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    trip_id: Mapped[int] = mapped_column(sa.ForeignKey("trips.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"))
    destination: Mapped[Optional[str]] = mapped_column(sa.String(120))
    start_date: Mapped[Optional[date]] = mapped_column(sa.Date)
    end_date: Mapped[Optional[date]] = mapped_column(sa.Date)
    trip_days: Mapped[Optional[int]] = mapped_column()
    interests: Mapped[list] = mapped_column(sa.JSON, default=list)
    budget_min: Mapped[Optional[float]] = mapped_column(sa.Numeric(14, 2))
    budget_max: Mapped[Optional[float]] = mapped_column(sa.Numeric(14, 2))
    accommodation: Mapped[Optional[str]] = mapped_column(sa.String(200))
    dietary: Mapped[Optional[str]] = mapped_column(sa.Text)
    restrictions: Mapped[Optional[str]] = mapped_column(sa.Text)
    notes: Mapped[Optional[str]] = mapped_column(sa.Text)
    sources: Mapped[dict] = mapped_column(sa.JSON, default=dict)  # field -> "direct" | "ai"
    updated_at: Mapped[datetime] = mapped_column(TS, default=utcnow, onupdate=utcnow)

    user: Mapped[User] = relationship()


class PreferenceSuggestion(Base):
    """Preferences the AI inferred from chat. Pending until the member reviews them."""
    __tablename__ = "preference_suggestions"
    id: Mapped[int] = mapped_column(primary_key=True)
    trip_id: Mapped[int] = mapped_column(sa.ForeignKey("trips.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"))
    message_id: Mapped[Optional[int]] = mapped_column(sa.ForeignKey("messages.id", ondelete="SET NULL"))
    data: Mapped[dict] = mapped_column(sa.JSON, default=dict)
    confidence: Mapped[Optional[float]] = mapped_column()
    status: Mapped[str] = mapped_column(sa.String(12), default="pending")  # pending | accepted | dismissed
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(TS)


class Conflict(Base):
    __tablename__ = "conflicts"
    id: Mapped[int] = mapped_column(primary_key=True)
    trip_id: Mapped[int] = mapped_column(sa.ForeignKey("trips.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(sa.String(30))
    title: Mapped[str] = mapped_column(sa.String(200))
    description: Mapped[str] = mapped_column(sa.Text)
    positions: Mapped[list] = mapped_column(sa.JSON, default=list)
    suggestion: Mapped[Optional[str]] = mapped_column(sa.Text)
    status: Mapped[str] = mapped_column(sa.String(12), default="open")  # open | accepted | dismissed
    votes: Mapped[dict] = mapped_column(sa.JSON, default=dict)  # user_id -> agree | disagree
    generated_by: Mapped[str] = mapped_column(sa.String(10), default="rules")  # rules | ai
    signature: Mapped[Optional[str]] = mapped_column(sa.String(64))  # fingerprint of the positions that produced it
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    decided_at: Mapped[Optional[datetime]] = mapped_column(TS)
    decided_by_id: Mapped[Optional[int]] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"))


class Itinerary(Base):
    __tablename__ = "itineraries"
    __table_args__ = (sa.UniqueConstraint("trip_id", "version", name="uq_itinerary_version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    trip_id: Mapped[int] = mapped_column(sa.ForeignKey("trips.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column()
    status: Mapped[str] = mapped_column(sa.String(12), default="running")  # running | succeeded | failed
    plan_markdown: Mapped[Optional[str]] = mapped_column(sa.Text)
    research_markdown: Mapped[Optional[str]] = mapped_column(sa.Text)
    days: Mapped[dict] = mapped_column(sa.JSON, default=dict)
    transcript: Mapped[list] = mapped_column(sa.JSON, default=list)
    budget_items: Mapped[Optional[list]] = mapped_column(sa.JSON)
    budget_error: Mapped[Optional[str]] = mapped_column(sa.Text)
    search_used: Mapped[bool] = mapped_column(default=False)
    error: Mapped[Optional[str]] = mapped_column(sa.Text)
    model: Mapped[Optional[str]] = mapped_column(sa.String(80))
    instructions: Mapped[Optional[str]] = mapped_column(sa.Text)
    created_by_id: Mapped[Optional[int]] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(TS)


class ChecklistItem(Base):
    __tablename__ = "checklist_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    trip_id: Mapped[int] = mapped_column(sa.ForeignKey("trips.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(sa.String(300))
    done: Mapped[bool] = mapped_column(default=False)
    assignee_id: Mapped[Optional[int]] = mapped_column(sa.ForeignKey("users.id", ondelete="SET NULL"))
    position: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(TS)
