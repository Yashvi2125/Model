"""Channel adapter and unified message bus connecting Web and Telegram interfaces."""
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
from typing import Optional

from sqlalchemy import select

from server import runtime
from server.db import SessionLocal
from server.models import Message, Trip, User
from server.services import chat_ai
from server.services import messages as msgs

log = logging.getLogger("tripmate.bus")

_trip_locks: dict[int, asyncio.Lock] = {}
_telegram_sender_func = None


def set_telegram_sender(func):
    """Registers an async function to send messages to Telegram (telegram_chat_id, text)."""
    global _telegram_sender_func
    _telegram_sender_func = func


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

    # 2. Relay from Web -> Telegram group (prevent echo loops)
    if msg.channel == "web" and tg_chat_id and _telegram_sender_func:
        relay_text = f"💬 <b>{sender_name} (via web):</b>\n{clean_text}"
        try:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(_telegram_sender_func(tg_chat_id, relay_text))
            except RuntimeError:
                runtime.spawn(_telegram_sender_func(tg_chat_id, relay_text))
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not relay message to Telegram: %s", exc)

    # 3. AI triggers: extraction or mentions
    if chat_ai.is_ai_mention(clean_text):
        runtime.spawn(chat_ai.run_ai_mention(msg.trip_id, msg_id))
    elif chat_ai.should_auto_extract(clean_text):
        runtime.spawn(chat_ai.run_auto_extract(msg.trip_id, msg_id))

    return None
