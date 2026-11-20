"""Pydantic request/response schemas."""
import re
from datetime import date, datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

INTEREST_IDS = ["adventure", "nature", "beaches", "food", "culture", "shopping", "relaxation", "nightlife", "spiritual"]


def _clean(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    v = v.strip()
    return v or None


def _clean_interests(v: list[str]) -> list[str]:
    out: list[str] = []
    for item in v or []:
        item = (item or "").strip()[:40]
        if item and item.lower() not in [o.lower() for o in out]:
            out.append(item.lower() if item.lower() in INTEREST_IDS else item)
    return out[:20]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---- auth / users ------------------------------------------------------------
def validate_password_strength(v: str) -> str:
    if len(v) < 8 or len(v) > 128:
        raise ValueError("Password must be 8–128 characters long.")
    if not re.search(r"[A-Za-z]", v) or not re.search(r"\d", v):
        raise ValueError("Password must contain at least one letter and one number.")
    return v


class RegisterIn(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    password: str
    confirm_password: Optional[str] = None
    accept_terms: bool = False
    remember_me: bool = False

    @field_validator("name")
    @classmethod
    def _name(cls, v):
        v = v.strip()
        if len(v) < 2:
            raise ValueError("Please enter your full name.")
        return v

    @field_validator("password")
    @classmethod
    def _pw(cls, v):
        return validate_password_strength(v)

    @model_validator(mode="after")
    def _match(self):
        if self.confirm_password is not None and self.confirm_password != self.password:
            raise ValueError("Passwords do not match.")
        if not self.accept_terms:
            raise ValueError("You need to accept the terms to create an account.")
        return self


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    remember_me: bool = False


class UserOut(ORM):
    id: int
    name: str
    email: str
    created_at: datetime
    telegram_user_id: Optional[int] = None
    telegram_username: Optional[str] = None


class TelegramLinkCodeOut(BaseModel):
    code: str
    expires_at: datetime
    bot_username: str


class ProfileUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=100)
    email: Optional[EmailStr] = None


class PasswordChange(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _pw(cls, v):
        return validate_password_strength(v)


# ---- trips -------------------------------------------------------------------
class TripBase(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    destination: Optional[str] = Field(default=None, max_length=120)
    destination_undecided: bool = False
    start_date: date
    end_date: date
    travelers_count: int = Field(ge=1, le=50)
    budget_total: Optional[float] = Field(default=None, ge=0, le=1e9)
    budget_per_person: Optional[float] = Field(default=None, ge=0, le=1e9)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    budget_flexibility: Literal["strict", "flexible", "very_flexible"] = "flexible"
    interests: list[str] = []
    accommodation_pref: Optional[str] = Field(default=None, max_length=200)
    dietary: Optional[str] = Field(default=None, max_length=1000)
    accessibility: Optional[str] = Field(default=None, max_length=1000)
    constraints: Optional[str] = Field(default=None, max_length=1000)
    notes: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("name")
    @classmethod
    def _n(cls, v):
        return v.strip()

    @field_validator("destination", "accommodation_pref", "dietary", "accessibility", "constraints", "notes")
    @classmethod
    def _strip(cls, v):
        return _clean(v)

    @field_validator("currency")
    @classmethod
    def _cur(cls, v):
        return v.upper()

    @field_validator("interests")
    @classmethod
    def _int(cls, v):
        return _clean_interests(v)

    @model_validator(mode="after")
    def _check(self):
        if self.end_date < self.start_date:
            raise ValueError("Return date can't be before the departure date.")
        if (self.end_date - self.start_date).days > 60:
            raise ValueError("Trips longer than 60 days aren't supported.")
        if not self.destination and not self.destination_undecided:
            raise ValueError("Enter a destination, or mark it as undecided.")
        if self.destination_undecided and not self.destination:
            pass
        return self


class TripCreate(TripBase):
    pass


class TripUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    destination: Optional[str] = Field(default=None, max_length=120)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    travelers_count: Optional[int] = Field(default=None, ge=1, le=50)
    budget_total: Optional[float] = Field(default=None, ge=0, le=1e9)
    budget_per_person: Optional[float] = Field(default=None, ge=0, le=1e9)
    notes: Optional[str] = Field(default=None, max_length=2000)


class MemberOut(BaseModel):
    user_id: int
    name: str
    role: str
    channel_origin: str = "web"
    telegram_username: Optional[str] = None
    joined_at: datetime


class TripSummary(ORM):
    id: int
    code: str
    name: str
    destination: Optional[str]
    destination_undecided: bool
    start_date: date
    end_date: date
    travelers_count: int
    budget_total: Optional[float]
    budget_per_person: Optional[float]
    currency: str
    status: str
    member_count: int = 0
    my_role: str = "member"
    last_accessed_at: Optional[datetime] = None


class TripDetail(TripSummary):
    budget_flexibility: str
    interests: list[str]
    accommodation_pref: Optional[str]
    dietary: Optional[str]
    accessibility: Optional[str]
    constraints: Optional[str]
    notes: Optional[str]
    is_joinable: bool
    owner_id: int
    created_at: datetime
    members: list[MemberOut] = []


class TripPreview(BaseModel):
    code: str
    name: str
    destination: Optional[str]
    start_date: date
    end_date: date
    member_count: int
    owner_name: str
    already_member: bool
    trip_id: Optional[int] = None


class JoinIn(BaseModel):
    code: str = Field(min_length=4, max_length=20)


class JoiningIn(BaseModel):
    is_joinable: bool


# ---- chat --------------------------------------------------------------------
class MessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=4000)

    @field_validator("content")
    @classmethod
    def _c(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("Message can't be empty.")
        return v


class MessageOut(BaseModel):
    id: int
    trip_id: int
    kind: str
    channel: str = "web"
    external_message_id: Optional[str] = None
    sender_id: Optional[int]
    sender_name: str
    content: str
    meta: dict[str, Any] = {}
    created_at: datetime


# ---- preferences ---------------------------------------------------------------
class PreferenceIn(BaseModel):
    destination: Optional[str] = Field(default=None, max_length=120)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    trip_days: Optional[int] = Field(default=None, ge=1, le=60)
    interests: Optional[list[str]] = None
    budget_min: Optional[float] = Field(default=None, ge=0, le=1e9)
    budget_max: Optional[float] = Field(default=None, ge=0, le=1e9)
    accommodation: Optional[str] = Field(default=None, max_length=200)
    dietary: Optional[str] = Field(default=None, max_length=1000)
    restrictions: Optional[str] = Field(default=None, max_length=1000)
    notes: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("destination", "accommodation", "dietary", "restrictions", "notes")
    @classmethod
    def _strip(cls, v):
        return _clean(v)

    @field_validator("interests")
    @classmethod
    def _int(cls, v):
        return None if v is None else _clean_interests(v)

    @model_validator(mode="after")
    def _check(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("End date can't be before the start date.")
        if self.budget_min is not None and self.budget_max is not None and self.budget_max < self.budget_min:
            raise ValueError("Maximum budget can't be lower than the minimum.")
        return self


class PreferenceOut(BaseModel):
    user_id: int
    user_name: str
    is_me: bool
    destination: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    trip_days: Optional[int] = None
    interests: list[str] = []
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    accommodation: Optional[str] = None
    dietary: Optional[str] = None
    restrictions: Optional[str] = None
    notes: Optional[str] = None
    sources: dict[str, str] = {}
    missing: list[str] = []
    updated_at: Optional[datetime] = None


class SuggestionOut(ORM):
    id: int
    user_id: int
    message_id: Optional[int]
    data: dict[str, Any]
    confidence: Optional[float]
    status: str
    created_at: datetime


class PreferencesOverview(BaseModel):
    members: list[PreferenceOut]
    my_suggestions: list[SuggestionOut]
    pending_suggestions_total: int
    trip_missing: list[str]


# ---- conflicts -----------------------------------------------------------------
class ConflictOut(ORM):
    id: int
    kind: str
    title: str
    description: str
    positions: list[dict[str, Any]]
    suggestion: Optional[str]
    status: str
    votes: dict[str, str]
    generated_by: str
    created_at: datetime
    decided_at: Optional[datetime]


class ConflictsResult(BaseModel):
    conflicts: list[ConflictOut]
    member_count: int
    members_sharing: int = 0
    ai_error: Optional[str] = None


class VoteIn(BaseModel):
    vote: Literal["agree", "disagree"]


# ---- itinerary / budget ------------------------------------------------------------
class GenerateIn(BaseModel):
    instructions: Optional[str] = Field(default=None, max_length=1000)


class ItineraryOut(ORM):
    id: int
    trip_id: int
    version: int
    status: str
    plan_markdown: Optional[str]
    research_markdown: Optional[str]
    days: dict[str, Any]
    search_used: bool
    error: Optional[str]
    budget_error: Optional[str]
    model: Optional[str]
    instructions: Optional[str]
    created_at: datetime
    completed_at: Optional[datetime]


class ItineraryListItem(ORM):
    id: int
    version: int
    status: str
    created_at: datetime


class ChecklistIn(BaseModel):
    text: str = Field(min_length=1, max_length=300)
    assignee_id: Optional[int] = None


class ChecklistPatch(BaseModel):
    text: Optional[str] = Field(default=None, min_length=1, max_length=300)
    done: Optional[bool] = None
    assignee_id: Optional[int] = None
    clear_assignee: bool = False


class ChecklistOut(ORM):
    id: int
    text: str
    done: bool
    assignee_id: Optional[int]
    position: int
    completed_at: Optional[datetime]
