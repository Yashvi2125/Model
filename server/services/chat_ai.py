"""Decides which chat messages involve the AI, and runs the Preference Extraction + reply agents in the background."""
import asyncio
import logging
import re
from typing import Optional

from sqlalchemy import select

from server.ai import agents
from server.ai.client import AIError, ai_status, friendly_error
from server.config import get_settings
from server.db import SessionLocal
from server.models import Message, Trip, TripMember, User
from server.services import messages as msgs
from server.services import preferences as prefs
from server.services.context import trip_context
from server.services.realtime import publish

log = logging.getLogger("tripmate.chat_ai")

MENTION_RE = re.compile(r"(?<![\w@])@(ai|tripmate[\w]*|bot|[\w]+_bot)\b", re.IGNORECASE)
SIGNAL_RE = re.compile(
    r"(budget|₹|\brs\.?\s?\d|\binr\b|\$\s?\d|\b\d[\d,]*\s?(k|rupees|per person|pp)\b|\bprefer|\bi (want|love|like|hate|need)\b|"
    r"\bavoid|can'?t eat|vegetarian|vegan|jain|halal|allerg|\b\d+[- ]?(day|night)s?\b|trip to|visit|going to|"
    r"beach|trek|hik|temple|museum|heritage|histor|nightlife|shopping|relax|adventure|hotel|resort|hostel|homestay|villa)",
    re.IGNORECASE)


def is_ai_mention(text: str, meta: Optional[dict] = None) -> bool:
    if meta and meta.get("ai_mention"):
        return True
    return bool(MENTION_RE.search(text or ""))


def looks_like_preference(text: str) -> bool:
    return len(text.strip()) >= 12 and bool(SIGNAL_RE.search(text))


def should_auto_extract(text: str) -> bool:
    settings = get_settings()
    is_qwen = getattr(settings, "llm_provider", "gemini").lower() == "qwen"
    is_gemini_ready = ai_status()["gemini_configured"]
    return settings.ai_auto_extract and (is_qwen or is_gemini_ready) and looks_like_preference(text)


def _clean_mention(text: str) -> str:
    return MENTION_RE.sub("", text).strip(" ,:-") or text


def _load(trip_id: int, message_id: int) -> Optional[dict]:
    with SessionLocal() as db:
        m = db.get(Message, message_id)
        trip = db.get(Trip, trip_id)
        if not m or not trip or not m.sender_id:
            return None
        sender = db.get(User, m.sender_id)
        rows = prefs.member_prefs(db, trip_id)
        recent = db.scalars(select(Message).where(Message.trip_id == trip_id, Message.id <= message_id)
                            .order_by(Message.id.desc()).limit(12)).all()
        recent_txt = "\n".join(f"{(r.sender.name if r.sender else 'MileMates AI')}: {r.content[:300]}"
                               for r in reversed(recent) if r.kind != "system")
        return {"ctx": trip_context(trip, rows), "sender": sender.name, "sender_id": sender.id, "text": m.content,
                "recent": recent_txt, "travelers": trip.travelers_count}


def _save_suggestion(trip_id: int, user_id: int, message_id: int, ex, travelers: int):
    data = prefs.fields_from_extracted(ex, travelers)
    with SessionLocal() as db:
        s = prefs.create_suggestion(db, trip_id, user_id, message_id, data, ex.confidence) if ex.confidence >= 0.3 else None
        db.commit()
        return (s.id, data) if s else (None, {})


def _describe(data: dict) -> str:
    labels = {"destination": "destination", "trip_days": "days", "start_date": "from", "end_date": "to",
              "budget_max": "budget/person", "interests": "interests", "accommodation": "stay", "dietary": "diet",
              "restrictions": "restrictions", "notes": "notes"}
    return "; ".join(f"{labels[k]}: {', '.join(v) if isinstance(v, list) else v}" for k, v in data.items() if k in labels)


async def run_ai_mention(trip_id: int, message_id: int) -> None:
    publish(trip_id, {"type": "ai_status", "state": "thinking"})
    try:
        ctx = await asyncio.to_thread(_load, trip_id, message_id)
        if not ctx:
            return
        text = _clean_mention(ctx["text"])
        sid, data = None, {}
        try:
            ex = await agents.extract_preferences(text, ctx["sender"], ctx["ctx"])
            sid, data = await asyncio.to_thread(_save_suggestion, trip_id, ctx["sender_id"], message_id, ex, ctx["travelers"])
            if sid:
                publish(trip_id, {"type": "preferences_updated"})
        except AIError as exc:
            if "isn't set up" in exc.user_message:
                raise
            log.info("Extraction skipped: %s", exc.user_message)
        reply = await agents.chat_reply(ctx["ctx"], ctx["recent"], ctx["sender"], text, _describe(data) if data else None)
        meta = {"suggestion_id": sid, "noted": data} if sid else {}
        await asyncio.to_thread(_post, trip_id, "ai", reply, meta)
    except Exception as exc:  # noqa: BLE001
        err = friendly_error(exc)
        await asyncio.to_thread(_post, trip_id, "ai", f"I couldn't answer that: {err.user_message}", {"error": True})
    finally:
        publish(trip_id, {"type": "ai_status", "state": "idle"})


async def run_auto_extract(trip_id: int, message_id: int) -> None:
    """Quiet background pass over ordinary chat: only ever creates *pending suggestions*."""
    try:
        ctx = await asyncio.to_thread(_load, trip_id, message_id)
        if not ctx:
            return

        settings = get_settings()
        if getattr(settings, "llm_provider", "gemini").lower() == "qwen":
            from server.ai.local_llm import classify_message_intent
            intent, latency_ms = await classify_message_intent(ctx["text"])
            if intent == "casual_chat":
                log.info("intent=casual_chat provider=qwen latency_ms=%d", latency_ms)
                return
            log.info("intent=%s provider=qwen latency_ms=%d", intent, latency_ms)

        ex = await agents.extract_preferences(ctx["text"], ctx["sender"], ctx["ctx"])
        sid, _ = await asyncio.to_thread(_save_suggestion, trip_id, ctx["sender_id"], message_id, ex, ctx["travelers"])
        if sid:
            publish(trip_id, {"type": "preferences_updated"})
    except Exception as exc:  # noqa: BLE001
        log.info("Auto-extraction skipped: %s", getattr(exc, "user_message", exc))


def _post(trip_id: int, kind: str, content: str, meta: dict):
    with SessionLocal() as db:
        m = msgs.post(db, trip_id, kind, content, None, meta)
        trip = db.get(Trip, trip_id)
        tg_chat_id = trip.telegram_group_chat_id if trip else None

    if tg_chat_id and kind == "ai":
        from server.services import message_bus
        message_bus.relay_ai_reply(trip_id, content, tg_chat_id)

    return m
