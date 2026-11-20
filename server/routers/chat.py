import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from server import runtime
from server.db import SessionLocal, get_db
from server.models import Message, TripMember
from server.schemas import MessageIn, MessageOut
from server.security import COOKIE_NAME, origin_allowed, rate_limit, user_from_token
from server.services import chat_ai
from server.services import message_bus
from server.services import messages as msgs
from server.services.access import TripAccess, trip_access
from server.services.realtime import manager

log = logging.getLogger("tripmate.chat")
router = APIRouter(tags=["chat"])


@router.get("/api/trips/{trip_id}/messages", response_model=list[MessageOut])
def list_messages(a: TripAccess = Depends(trip_access), db: Session = Depends(get_db),
                  after_id: Optional[int] = None, before_id: Optional[int] = None, limit: int = Query(100, ge=1, le=300)):
    q = select(Message).where(Message.trip_id == a.trip.id)
    if after_id:
        rows = db.scalars(q.where(Message.id > after_id).order_by(Message.id).limit(limit)).all()
    else:
        if before_id:
            q = q.where(Message.id < before_id)
        rows = list(reversed(db.scalars(q.order_by(Message.id.desc()).limit(limit)).all()))
    return [msgs.to_out(m) for m in rows]


@router.post("/api/trips/{trip_id}/messages", response_model=MessageOut, status_code=201)
def send_message(body: MessageIn, a: TripAccess = Depends(trip_access), db: Session = Depends(get_db)):
    rate_limit(f"msg:{a.user.id}", 40, 60)
    m = msgs.post(db, a.trip.id, "user", body.content, a.user.id, channel="web")
    if a.trip.telegram_group_chat_id:
        message_bus.relay_web_message(a.trip.id, a.user.name, body.content, a.trip.telegram_group_chat_id)
    if chat_ai.is_ai_mention(body.content):
        runtime.spawn(chat_ai.run_ai_mention(a.trip.id, m.id))
    elif chat_ai.should_auto_extract(body.content):
        runtime.spawn(chat_ai.run_auto_extract(a.trip.id, m.id))
    return msgs.to_out(m)


def _authorise_ws(token: Optional[str], trip_id: int) -> Optional[int]:
    with SessionLocal() as db:
        user = user_from_token(db, token)
        if not user:
            return None
        ok = db.scalar(select(TripMember.id).where(TripMember.trip_id == trip_id, TripMember.user_id == user.id))
        return user.id if ok else -1


@router.websocket("/api/ws/trips/{trip_id}")
async def trip_socket(ws: WebSocket, trip_id: int):
    if not origin_allowed(ws.headers.get("origin"), ws.headers.get("host")):
        await ws.close(code=4403)
        return
    uid = await run_in_threadpool(_authorise_ws, ws.cookies.get(COOKIE_NAME), trip_id)
    if uid is None:
        await ws.close(code=4401)  # not logged in / expired
        return
    if uid == -1:
        await ws.close(code=4403)  # logged in but not a member of this trip
        return
    await ws.accept()
    await manager.connect(trip_id, ws, uid)
    try:
        await ws.send_json({"type": "ready"})
        while True:
            data = await ws.receive_json()
            if isinstance(data, dict) and data.get("type") == "ping":
                await ws.send_json({"type": "pong"})
    except (WebSocketDisconnect, RuntimeError, ValueError):
        pass
    finally:
        await manager.disconnect(trip_id, ws)
