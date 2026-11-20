"""Channel adapter and unified message bus connecting Web and Telegram interfaces."""
import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
import html
import logging
import time
from typing import Optional

from sqlalchemy import select

from server import runtime
from server.config import get_settings
from server.db import SessionLocal
from server.models import Message, Trip, User
from server.services import chat_ai
from server.services import messages as msgs

log = logging.getLogger("tripmate.bus")

_trip_locks: dict[int, asyncio.Lock] = {}
_telegram_sender_func = None

# Sliding window rate limiter for web-to-telegram relay
_relay_history: dict[int, list[float]] = defaultdict(list)
RELAY_WINDOW_SECONDS = 10.0
RELAY_MAX_MESSAGES = 5


def check_can_relay(trip_id: int) -> bool:
    """Checks feature flag and sliding window rate limit for web-to-telegram relay."""
    settings = get_settings()
    if not settings.relay_web_to_telegram:
        return False
    now = time.monotonic()
    cutoff = now - RELAY_WINDOW_SECONDS
    timestamps = [t for t in _relay_history[trip_id] if t > cutoff]
    if len(timestamps) >= RELAY_MAX_MESSAGES:
        log.warning(
            "Rate limit exceeded for web-to-telegram relay on trip %s (max %s in %ss)",
            trip_id,
            RELAY_MAX_MESSAGES,
            RELAY_WINDOW_SECONDS,
        )
        _relay_history[trip_id] = timestamps
        return False
    timestamps.append(now)
    _relay_history[trip_id] = timestamps
    return True


def set_telegram_sender(func):
    """Registers an async function to send messages to Telegram (telegram_chat_id, text)."""
    global _telegram_sender_func
    _telegram_sender_func = func


def relay_web_message(trip_id: int, sender_name: str, text: str, tg_chat_id: Optional[int] = None) -> None:
    """Relays a message posted from the web UI to the bound Telegram group (subject to rate limiting & feature flag).
    Safely HTML-escapes content. Delivery failures log a warning and never affect saved web messages or responses.
    """
    if not tg_chat_id or not _telegram_sender_func:
        return
    if not check_can_relay(trip_id):
        return

    safe_name = html.escape((sender_name or "Member").strip())
    safe_text = html.escape((text or "").strip())
    if not safe_text:
        return
    relay_html = f"💬 <b>{safe_name} (via web):</b>\n{safe_text}"

    async def _safe_send():
        try:
            await _telegram_sender_func(tg_chat_id, relay_html)
        except Exception as exc:  # noqa: BLE001
            log.warning("Failed to deliver relay message to Telegram chat %s: %s", tg_chat_id, type(exc).__name__)

    try:
        runtime.spawn(_safe_send())
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not schedule Telegram relay task for chat %s: %s", tg_chat_id, type(exc).__name__)


def get_trip_lock(trip_id: int) -> asyncio.Lock:
    if trip_id not in _trip_locks:
        _trip_locks[trip_id] = asyncio.Lock()
    return _trip_locks[trip_id]


@dataclass
class IncomingMessage:
    trip_id: int
    text: str
    channel: str  # "telegram" | "web"
    user_id: Optional[int] = None
    member_id: Optional[int] = None
    external_message_id: Optional[str] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    meta: dict = field(default_factory=dict)
    sender_name: Optional[str] = None


async def handle_incoming_message(msg: IncomingMessage) -> Message:
    """Unified entry point for messages from any channel.

    1. Persists message in DB with channel tag.
    2. Broadcasts to Web via WebSocket.
    3. If from Web, relays to Telegram group (if connected).
    4. Evaluates background AI triggers (preference extraction, mentions).
    """
    clean_text = msg.text.strip()
    if not clean_text:
        return None

    # 1. Save in database and broadcast to WebSocket
    def _save():
        with SessionLocal() as db:
            m = msgs.post(
                db=db,
                trip_id=msg.trip_id,
                kind="user",
                content=clean_text,
                sender_id=msg.user_id,
                meta={**(msg.meta or {}), "channel": msg.channel},
                channel=msg.channel,
                external_message_id=msg.external_message_id,
            )
            trip = db.get(Trip, msg.trip_id)
            tg_chat_id = trip.telegram_group_chat_id if trip else None
            sender = db.get(User, msg.user_id) if msg.user_id else None
            sender_name = msg.sender_name or (sender.name if sender else "Member")
            return m.id, tg_chat_id, sender_name

    msg_id, tg_chat_id, sender_name = await asyncio.to_thread(_save)

    # 2. Relay from Web -> Telegram group (prevent echo loops and rate limit)
    if msg.channel == "web" and tg_chat_id:
        relay_web_message(msg.trip_id, sender_name, clean_text, tg_chat_id)

    # 3. AI triggers: extraction or mentions
    if chat_ai.is_ai_mention(clean_text):
        runtime.spawn(chat_ai.run_ai_mention(msg.trip_id, msg_id))
    elif chat_ai.should_auto_extract(clean_text):
        runtime.spawn(chat_ai.run_auto_extract(msg.trip_id, msg_id))

    return None
