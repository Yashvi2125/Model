"""Create, serialise and broadcast chat messages."""
from typing import Optional

from sqlalchemy.orm import Session

from server.models import Message
from server.schemas import MessageOut
from server.services.realtime import publish


def to_out(m: Message) -> MessageOut:
    name = m.sender.name if m.sender else ("MileMates AI" if m.kind == "ai" else "MileMates")
    return MessageOut(
        id=m.id,
        trip_id=m.trip_id,
        kind=m.kind,
        channel=getattr(m, "channel", "web") or "web",
        external_message_id=getattr(m, "external_message_id", None),
        sender_id=m.sender_id,
        sender_name=name,
        content=m.content,
        meta=m.meta or {},
        created_at=m.created_at,
    )


def post(
    db: Session,
    trip_id: int,
    kind: str,
    content: str,
    sender_id: Optional[int] = None,
    meta: Optional[dict] = None,
    channel: str = "web",
    external_message_id: Optional[str] = None,
) -> Message:
    m = Message(
        trip_id=trip_id,
        kind=kind,
        content=content,
        sender_id=sender_id,
        meta=meta or {},
        channel=channel,
        external_message_id=external_message_id,
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    publish(trip_id, {"type": "message", "message": to_out(m).model_dump(mode="json")})
    return m
