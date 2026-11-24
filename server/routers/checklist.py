from typing import Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from server.db import get_db
from server.models import ChecklistItem, utcnow
from server.schemas import ChecklistIn, ChecklistOut, ChecklistPatch
from server.services.access import TripAccess, get_member_ids, trip_access

router = APIRouter(prefix="/api/trips/{trip_id}/checklist", tags=["checklist"])


class ChecklistGenerateIn(BaseModel):
    focus: Optional[str] = None


class ChecklistGenerateOut(BaseModel):
    added: int
    provider: str
    items: list[ChecklistOut]


def _item(db: Session, a: TripAccess, iid: int) -> ChecklistItem:
    it = db.get(ChecklistItem, iid)
    if not it or it.trip_id != a.trip.id:
        raise HTTPException(404, "Checklist item not found.")
    return it


def _check_assignee(db: Session, a: TripAccess, uid):
    if uid is not None and uid not in get_member_ids(db, a.trip.id):
        raise HTTPException(400, "You can only assign items to members of this trip.")


@router.get("", response_model=list[ChecklistOut])
def list_items(a: TripAccess = Depends(trip_access), db: Session = Depends(get_db)):
    return db.scalars(select(ChecklistItem).where(ChecklistItem.trip_id == a.trip.id)
                      .order_by(ChecklistItem.position, ChecklistItem.id)).all()


@router.post("", response_model=ChecklistOut, status_code=201)
def add_item(body: ChecklistIn, a: TripAccess = Depends(trip_access), db: Session = Depends(get_db)):
    _check_assignee(db, a, body.assignee_id)
    pos = (db.scalar(select(func.max(ChecklistItem.position)).where(ChecklistItem.trip_id == a.trip.id)) or 0) + 1
    it = ChecklistItem(trip_id=a.trip.id, text=body.text.strip(), assignee_id=body.assignee_id, position=pos)
    db.add(it)
    db.commit()
    return it


@router.patch("/{iid}", response_model=ChecklistOut)
def patch_item(iid: int, body: ChecklistPatch, a: TripAccess = Depends(trip_access), db: Session = Depends(get_db)):
    it = _item(db, a, iid)
    if body.text is not None:
        it.text = body.text.strip()
    if body.done is not None:
        it.done, it.completed_at = body.done, (utcnow() if body.done else None)
    if body.clear_assignee:
        it.assignee_id = None
    elif body.assignee_id is not None:
        _check_assignee(db, a, body.assignee_id)
        it.assignee_id = body.assignee_id
    db.commit()
    return it


@router.delete("/{iid}", status_code=204)
def delete_item(iid: int, a: TripAccess = Depends(trip_access), db: Session = Depends(get_db)):
    db.delete(_item(db, a, iid))
    db.commit()


@router.post("/generate", response_model=ChecklistGenerateOut, status_code=201)
async def generate_packing(
    body: Optional[ChecklistGenerateIn] = None,
    a: TripAccess = Depends(trip_access),
    db: Session = Depends(get_db),
):
    from server.services.context import trip_context
    from server.services import preferences as prefs_svc
    from server.ai.local_llm import generate_packing_list

    pref_rows = prefs_svc.member_prefs(db, a.trip.id)
    ctx = trip_context(a.trip, pref_rows)
    focus = body.focus if body else None

    raw_items, provider = await generate_packing_list(ctx, focus=focus)

    pos = (db.scalar(select(func.max(ChecklistItem.position)).where(ChecklistItem.trip_id == a.trip.id)) or 0)
    created = []
    for idx, item in enumerate(raw_items, 1):
        cat = item.get("category", "").strip()
        txt = item.get("text", "").strip()
        if not txt:
            continue
        formatted_text = f"[{cat.title()}] {txt}" if cat else txt
        it = ChecklistItem(trip_id=a.trip.id, text=formatted_text, position=pos + idx)
        db.add(it)
        created.append(it)

    db.commit()
    for it in created:
        db.refresh(it)

    return {
        "added": len(created),
        "provider": provider,
        "items": [ChecklistOut.model_validate(it) for it in created],
    }
