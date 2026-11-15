import hashlib
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from server.ai import agents
from server.ai.client import AIError, friendly_error
from server.db import get_db
from server.models import Conflict, Message, utcnow
from server.schemas import ConflictOut, ConflictsResult, VoteIn
from server.services import conflicts as rules
from server.services import messages as msgs
from server.services import preferences as prefs
from server.services.access import TripAccess, get_member_ids, trip_access
from server.services.context import trip_context
from server.services.realtime import publish

log = logging.getLogger("tripmate.conflicts")
router = APIRouter(prefix="/api/trips/{trip_id}/conflicts", tags=["conflicts"])

CHAT_SCAN_LIMIT = 40


def _list(db: Session, a: TripAccess, ai_error=None) -> ConflictsResult:
    rows = db.scalars(select(Conflict).where(Conflict.trip_id == a.trip.id, Conflict.status != "dismissed")
                      .order_by(Conflict.id)).all()
    sharing = sum(1 for _, p in prefs.member_prefs(db, a.trip.id) if p and (
        p.interests or p.budget_max is not None or p.destination or p.start_date or p.accommodation or p.notes))
    return ConflictsResult(conflicts=[ConflictOut.model_validate(c) for c in rows],
                           member_count=len(get_member_ids(db, a.trip.id)), members_sharing=sharing, ai_error=ai_error)


@router.get("", response_model=ConflictsResult)
async def list_conflicts(a: TripAccess = Depends(trip_access), db: Session = Depends(get_db)):
    res = _list(db, a)
    # If no conflicts exist yet and at least 2 members have shared preferences,
    # auto-run analyze once so the Conflicts tab immediately has data!
    if not res.conflicts and res.members_sharing >= 2:
        return await analyze(a, db)
    return res


@router.post("/analyze", response_model=ConflictsResult)
async def analyze(a: TripAccess = Depends(trip_access), db: Session = Depends(get_db)):
    trip_id, currency = a.trip.id, a.trip.currency
    rows = prefs.member_prefs(db, trip_id)
    detected = rules.detect(rows, currency)

    decided = {(c.kind, c.signature) for c in db.scalars(select(Conflict).where(
        Conflict.trip_id == trip_id, Conflict.status.in_(["accepted", "dismissed"])))}
    db.execute(delete(Conflict).where(Conflict.trip_id == trip_id, Conflict.status == "open"))
    fresh = [c for c in detected if (c["kind"], c["signature"]) not in decided]

    # Map member names to user IDs for positions
    member_map = {u.name.lower().split()[0]: u.id for u, _ in rows}
    member_map.update({u.name.lower(): u.id for u, _ in rows})

    # Load recent chat messages
    chat_text = ""
    try:
        recent_msgs = db.scalars(
            select(Message)
            .where(Message.trip_id == trip_id, Message.kind != "system")
            .order_by(Message.id.desc())
            .limit(CHAT_SCAN_LIMIT)
        ).all()
        if recent_msgs:
            chat_lines = [f"{(m.sender.name if m.sender else 'TripMate AI')}: {m.content[:300]}"
                          for m in reversed(recent_msgs)]
            chat_text = "\n".join(chat_lines)
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not load chat for conflict analysis: %s", exc)

    ai_error = None
    suggestions: dict[str, str] = {}
    additional: list[dict] = []

    # ALWAYS run the AI Conflict Resolution engine!
    # Even if rule engine found 0 structural clashes, member notes, dietary requirements,
    # or chat discussions may contain active conflicts (e.g. Day 2 Shibuya vs Day 2 Beach).
    try:
        result = await agents.resolve_conflicts(trip_context(a.trip, rows), fresh, chat_text)
        raw_sug = result.get("suggestions") if isinstance(result.get("suggestions"), dict) else {}
        suggestions = {k: str(v)[:1200] for k, v in raw_sug.items() if isinstance(v, str)}

        raw_add = result.get("additional") or result.get("conflicts") or []
        if isinstance(raw_add, list):
            additional = [x for x in raw_add if isinstance(x, dict)][:5]
    except Exception as exc:  # noqa: BLE001
        ai_error = friendly_error(exc).user_message

    # 1. Persist rule-detected conflicts with their AI-suggested compromises
    for c in fresh:
        sug = suggestions.get(c["kind"])
        db.add(Conflict(
            trip_id=trip_id,
            kind=c["kind"],
            title=c["title"],
            description=c["description"],
            positions=c["positions"],
            suggestion=sug,
            generated_by="ai" if sug else "rules",
            signature=c["signature"]
        ))

    # 2. Persist AI-detected additional / latent conflicts
    rule_titles_lower = [c["title"].lower() for c in fresh]
    for x in additional:
        title = str(x.get("title", "")).strip()[:200]
        if not title:
            continue
        # Skip if already covered by a rule-detected conflict
        if any(title.lower() in t or t in title.lower() for t in rule_titles_lower):
            continue
        import re
        ai_days = re.findall(r"\bday\s*\d+\b", title.lower())
        if ai_days and any(d in t for t in rule_titles_lower for d in ai_days):
            continue

        kind = str(x.get("kind", "activities")).lower()[:30]
        if kind not in ("activities", "schedule", "dates", "budget", "accommodation", "dietary", "other"):
            kind = "activities"
        sig = hashlib.sha256(f"{kind}:{title}".encode()).hexdigest()[:32]
        if (kind, sig) not in decided and ("other", sig) not in decided:
            # Format positions
            raw_pos = x.get("positions") or []
            positions = []
            if isinstance(raw_pos, list):
                for p in raw_pos:
                    if isinstance(p, dict):
                        p_name = str(p.get("name", "")).strip()
                        p_det = str(p.get("detail", "")).strip()
                        uid = member_map.get(p_name.lower().split()[0]) or member_map.get(p_name.lower())
                        pos_dict = {"name": p_name, "detail": p_det}
                        if uid:
                            pos_dict["user_id"] = uid
                        positions.append(pos_dict)

            db.add(Conflict(
                trip_id=trip_id,
                kind=kind,
                title=title,
                description=str(x.get("description", ""))[:1200],
                positions=positions,
                suggestion=str(x.get("suggestion", ""))[:1200] or None,
                generated_by="ai",
                signature=sig
            ))

    db.commit()
    publish(trip_id, {"type": "conflicts_updated"})
    return _list(db, a, ai_error)


def _get(db: Session, a: TripAccess, cid: int) -> Conflict:
    c = db.get(Conflict, cid)
    if not c or c.trip_id != a.trip.id:
        raise HTTPException(404, "Conflict not found.")
    return c


@router.post("/{cid}/vote", response_model=ConflictsResult)
def vote(cid: int, body: VoteIn, a: TripAccess = Depends(trip_access), db: Session = Depends(get_db)):
    c = _get(db, a, cid)
    if c.status == "dismissed":
        raise HTTPException(409, "This item was dismissed.")
    if not c.suggestion:
        raise HTTPException(400, "No compromise has been proposed for this yet.")
    votes = dict(c.votes or {})
    votes[str(a.user.id)] = body.vote
    c.votes = votes
    members = get_member_ids(db, a.trip.id)
    all_agree = all(votes.get(str(m)) == "agree" for m in members)
    was = c.status
    c.status = "accepted" if all_agree else "open"
    c.decided_at, c.decided_by_id = (utcnow(), a.user.id) if all_agree else (None, None)
    db.commit()
    if all_agree and was != "accepted":
        msgs.post(db, a.trip.id, "system", f"Everyone agreed on a compromise for “{c.title}”: {c.suggestion}")
    publish(a.trip.id, {"type": "conflicts_updated"})
    return _list(db, a)


@router.post("/{cid}/discuss", response_model=ConflictsResult)
def discuss(cid: int, a: TripAccess = Depends(trip_access), db: Session = Depends(get_db)):
    c = _get(db, a, cid)
    text = f"Let's talk about this: {c.title}." + (f" Suggested compromise: {c.suggestion}" if c.suggestion else "")
    msgs.post(db, a.trip.id, "user", text[:3900], a.user.id, {"conflict_id": c.id})
    return _list(db, a)


@router.post("/{cid}/dismiss", response_model=ConflictsResult)
def dismiss(cid: int, a: TripAccess = Depends(trip_access), db: Session = Depends(get_db)):
    a.require_owner()
    c = _get(db, a, cid)
    c.status, c.decided_at, c.decided_by_id = "dismissed", utcnow(), a.user.id
    db.commit()
    publish(a.trip.id, {"type": "conflicts_updated"})
    return _list(db, a)
