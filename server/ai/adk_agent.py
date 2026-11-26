"""Google Agent Development Kit (ADK) Travel Advisor Agent.

Connects Gemini API and Google ADK directly to MileMates backend services, database,
and Telegraph publishing.
"""
import asyncio
from datetime import date, datetime, timedelta
import logging
import os
import re
from typing import Optional

from dotenv import load_dotenv
import google.adk as adk
from google.adk.sessions import InMemorySessionService
from google.genai import types
from sqlalchemy import select

from server.config import get_settings
from server.db import SessionLocal
from server.models import Conflict, Itinerary, Preference, Trip, TripMember, User, utcnow
from server.routers.trips import CODE_ALPHABET, new_code, normalise_code
from server.services import itinerary_service as itin_svc
from server.services import preferences as pref_svc
from server.telegram.telegraph import publish_itinerary_page

load_dotenv()
log = logging.getLogger("tripmate.adk")

# Ensure both keys are present in env for google-genai and adk
if not os.environ.get("GOOGLE_API_KEY") and os.environ.get("GEMINI_API_KEY"):
    os.environ["GOOGLE_API_KEY"] = os.environ["GEMINI_API_KEY"]
elif not os.environ.get("GEMINI_API_KEY") and os.environ.get("GOOGLE_API_KEY"):
    os.environ["GEMINI_API_KEY"] = os.environ["GOOGLE_API_KEY"]


def _find_trip(db, trip_code_or_id: str) -> Optional[Trip]:
    trip_str = str(trip_code_or_id).strip()
    if trip_str.isdigit():
        t = db.get(Trip, int(trip_str))
        if t:
            return t
    norm = normalise_code(trip_str)
    return db.scalar(select(Trip).where((Trip.code == norm) | (Trip.trip_code == norm)))


# --- ADK Function Tools --------------------------------------------------------

def create_trip(
    name: str,
    destination: str,
    start_date: str,
    end_date: str,
    travelers_count: int = 2,
    budget_per_person: Optional[float] = None,
    creator_telegram_id: Optional[int] = None,
    creator_name: Optional[str] = None,
) -> str:
    """Creates a new trip and returns its unique Trip Code and details.

    Dates should be in YYYY-MM-DD format.
    """
    try:
        s_date = datetime.strptime(start_date.strip(), "%Y-%m-%d").date()
        e_date = datetime.strptime(end_date.strip(), "%Y-%m-%d").date()
    except Exception:
        s_date = date.today() + timedelta(days=14)
        e_date = s_date + timedelta(days=5)

    with SessionLocal() as db:
        user_id = 1
        if creator_telegram_id:
            from server.telegram.identity import get_or_create_telegram_user
            u = get_or_create_telegram_user(
                db, creator_telegram_id, creator_name or f"TG User {creator_telegram_id}"
            )
            user_id = u.id

        code = new_code(db)
        trip = Trip(
            name=name[:120],
            destination=destination[:120],
            code=code,
            trip_code=code,
            start_date=s_date,
            end_date=e_date,
            travelers_count=max(1, travelers_count),
            budget_per_person=budget_per_person,
            owner_id=user_id,
        )
        db.add(trip)
        db.flush()
        db.add(TripMember(trip_id=trip.id, user_id=user_id, role="owner", last_accessed_at=utcnow()))
        pref_svc.seed_from_trip(db, trip, user_id)
        db.commit()
        return f"Trip '{trip.name}' created successfully! Trip Code: {trip.code}. Destination: {trip.destination}, Dates: {trip.start_date} to {trip.end_date}."


def join_trip_by_code(trip_code: str, telegram_user_id: int, user_name: str) -> str:
    """Joins an existing trip using its trip code."""
    with SessionLocal() as db:
        trip = _find_trip(db, trip_code)
        if not trip:
            return f"No trip found with code '{trip_code}'."
        from server.telegram.identity import ensure_trip_member, get_or_create_telegram_user
        u = get_or_create_telegram_user(db, telegram_user_id, user_name)
        ensure_trip_member(db, trip.id, u.id, tg_user_id=telegram_user_id, tg_username=None)
        return f"Joined trip '{trip.name}' (Code: {trip.code}) to {trip.destination}!"


def get_trip_details(trip_code_or_id: str) -> str:
    """Retrieves destination, dates, member count, and status for a trip."""
    with SessionLocal() as db:
        trip = _find_trip(db, trip_code_or_id)
        if not trip:
            return f"Trip '{trip_code_or_id}' not found."
        m_count = len(trip.members)
        budget = f"{trip.currency} {trip.budget_per_person:.2f}" if trip.budget_per_person else "Flexible"
        return (
            f"Trip: {trip.name} (Code: {trip.code})\n"
            f"Destination: {trip.destination or 'Undecided'}\n"
            f"Dates: {trip.start_date} to {trip.end_date} ({(trip.end_date - trip.start_date).days + 1} days)\n"
            f"Members: {m_count} joined\n"
            f"Budget/person: {budget}\n"
            f"Status: {trip.status}"
        )


def get_trip_members_and_preferences(trip_code_or_id: str) -> str:
    """Lists trip members and their saved travel preferences."""
    with SessionLocal() as db:
        trip = _find_trip(db, trip_code_or_id)
        if not trip:
            return f"Trip '{trip_code_or_id}' not found."
        rows = pref_svc.member_prefs(db, trip.id)
        out = [f"Preferences for {trip.name}:"]
        for u, p in rows:
            interests = ", ".join(p.interests) if p and p.interests else "None specified"
            budget = f"Up to {p.budget_max}" if p and p.budget_max else "Not specified"
            notes = f"; Notes: {p.notes}" if p and p.notes else ""
            out.append(f"- {u.name}: Interests: {interests}; Budget: {budget}{notes}")
        return "\n".join(out)


def get_or_create_itinerary_summary(trip_code_or_id: str) -> str:
    """Returns the latest itinerary or plan summary for the trip."""
    with SessionLocal() as db:
        trip = _find_trip(db, trip_code_or_id)
        if not trip:
            return f"Trip '{trip_code_or_id}' not found."
        latest = db.scalar(
            select(Itinerary)
            .where(Itinerary.trip_id == trip.id, Itinerary.status == "succeeded")
            .order_by(Itinerary.version.desc())
        )
        if latest and latest.plan_markdown:
            return f"Itinerary v{latest.version} for {trip.destination}:\n\n{latest.plan_markdown[:1500]}..."
        return f"No itinerary has been generated for {trip.name} yet. Run /plan in the group to generate one!"


# --- Google ADK Agent Setup ----------------------------------------------------

ADK_TOOLS = [
    create_trip,
    join_trip_by_code,
    get_trip_details,
    get_trip_members_and_preferences,
    get_or_create_itinerary_summary,
]

ADK_INSTRUCTION = (
    "You are the MileMates Travel Advisor & Coordinator, an expert AI assistant designed to help groups "
    "plan seamless trips. You are accessible via Telegram and Web.\n"
    "Your responsibilities:\n"
    "1. Recommend destinations, sights, hotels, and local food tailored to group preferences.\n"
    "2. Manage trip details (dates, travelers, budget, interests) using available tools.\n"
    "3. Keep responses structured, concise, conversational, and enthusiastic.\n"
    "4. Use bullet points and emoji when helpful, and avoid raw JSON output in chat."
)

_adk_agent: Optional[adk.Agent] = None
_adk_runner: Optional[adk.Runner] = None
_session_service: Optional[InMemorySessionService] = None


def get_adk_runner() -> adk.Runner:
    global _adk_agent, _adk_runner, _session_service
    if _adk_runner is not None:
        return _adk_runner

    model_name = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")

    _session_service = InMemorySessionService()
    _adk_agent = adk.Agent(
        name="tripmate_advisor",
        model=model_name,
        instruction=ADK_INSTRUCTION,
        tools=ADK_TOOLS,
    )
    _adk_runner = adk.Runner(
        app_name="tripmate",
        agent=_adk_agent,
        session_service=_session_service,
        auto_create_session=True,
    )
    return _adk_runner


async def ask_adk_advisor(user_id: str, session_id: str, prompt: str) -> str:
    """Interacts with the Google ADK Travel Advisor Agent maintaining session memory."""
    from server.ai.gateway import gateway

    runner = get_adk_runner()
    model_name = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
    content = types.Content(
        role="user",
        parts=[types.Part.from_text(text=prompt)],
    )
    accumulated_texts = []

    async def _run_stream():
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=content,
        ):
            if event.content and event.content.parts:
                for p in event.content.parts:
                    if p.text:
                        accumulated_texts.append(p.text)

    try:
        await asyncio.wait_for(_run_stream(), timeout=60.0)
        if gateway.is_enabled():
            gateway.record_call(feature="adk_agent", model=model_name, status=200)
    except asyncio.TimeoutError:
        log.warning("ADK runner timed out after 60s for user %s", user_id)
        if gateway.is_enabled():
            gateway.record_call(feature="adk_agent", model=model_name, status="timeout")
        return "I took too long to think about that. Please ask a shorter question or try again."
    except Exception as exc:  # noqa: BLE001
        log.warning("ADK runner execution error: %s", exc)
        if gateway.is_enabled():
            gateway.record_call(feature="adk_agent", model=model_name, status="error")
        return f"I ran into an issue answering that: {exc}"

    full_reply = "".join(accumulated_texts).strip()
    return full_reply or "I'm here to help you plan your trip! Ask me about destinations, itineraries, or budgets."
