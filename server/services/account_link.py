"""Account linking service: bridges Web accounts with Telegram identities and merges synthetic users."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import hmac
import logging
import secrets
from typing import Optional, Tuple

import sqlalchemy as sa
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from server.models import (
    Preference,
    TelegramLinkCode,
    Trip,
    TripMember,
    User,
    utcnow,
)

log = logging.getLogger("tripmate.account_link")

LINK_CODE_CHARS = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
CODE_LENGTH = 8
CODE_EXPIRE_MINUTES = 10
MAX_FAILURES = 5
LOCKOUT_WINDOW_SECONDS = 900  # 15 minutes

# Rate limiting failed /link attempts: tg_user_id -> list of timestamps
_failed_link_attempts: dict[int, list[float]] = defaultdict(list)


def is_rate_limited(tg_user_id: int) -> bool:
    """Checks whether a Telegram user has exceeded failed link attempts in the sliding window."""
    now = datetime.now(timezone.utc).timestamp()
    cutoff = now - LOCKOUT_WINDOW_SECONDS
    attempts = [t for t in _failed_link_attempts[tg_user_id] if t > cutoff]
    _failed_link_attempts[tg_user_id] = attempts
    return len(attempts) >= MAX_FAILURES


def record_failed_attempt(tg_user_id: int) -> None:
    """Records an invalid /link attempt."""
    now = datetime.now(timezone.utc).timestamp()
    _failed_link_attempts[tg_user_id].append(now)


def clear_failed_attempts(tg_user_id: int) -> None:
    """Clears failed attempts upon successful link."""
    _failed_link_attempts.pop(tg_user_id, None)


def generate_link_code(db: Session, user_id: int) -> str:
    """Generates an 8-character unambiguous one-time link code valid for 10 minutes."""
    # Invalidate any previously active unused codes for this user
    now = utcnow()
    active_codes = db.scalars(
        select(TelegramLinkCode).where(
            TelegramLinkCode.user_id == user_id,
            TelegramLinkCode.used_at.is_(None),
            TelegramLinkCode.expires_at > now,
        )
    ).all()
    for ac in active_codes:
        ac.used_at = now

    code = "".join(secrets.choice(LINK_CODE_CHARS) for _ in range(CODE_LENGTH))
    record = TelegramLinkCode(
        user_id=user_id,
        code=code,
        created_at=now,
        expires_at=now + timedelta(minutes=CODE_EXPIRE_MINUTES),
        used_at=None,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return code


def get_user_referencing_columns(bind_or_session) -> list[Tuple[str, str]]:
    """Discovers every (table_name, column_name) in the database that has a foreign key referencing users.id."""
    insp = inspect(bind_or_session)
    refs: list[Tuple[str, str]] = []
    for table_name in insp.get_table_names():
        for fk in insp.get_foreign_keys(table_name):
            if fk.get("referred_table") == "users":
                referred_cols = fk.get("referred_columns") or []
                constrained_cols = fk.get("constrained_columns") or []
                for col, ref in zip(constrained_cols, referred_cols):
                    if ref == "id":
                        refs.append((table_name, col))
    return refs


def merge_preferences(db: Session, web_pref: Preference, tg_pref: Preference) -> None:
    """Merges fields from tg_pref into web_pref:
    - Keep web row.
    - Fill empty fields in web row from tg_pref.
    - If both have values and they differ, prefer the more recently updated value.
    - Merge interests lists and sources dicts.
    - Deletes tg_pref.
    """
    web_dt = web_pref.updated_at or datetime.min.replace(tzinfo=timezone.utc)
    tg_dt = tg_pref.updated_at or datetime.min.replace(tzinfo=timezone.utc)
    prefer_tg = tg_dt > web_dt

    scalar_fields = [
        "destination", "start_date", "end_date", "trip_days",
        "budget_min", "budget_max", "accommodation", "dietary",
        "restrictions", "notes",
    ]
    for field in scalar_fields:
        w_val = getattr(web_pref, field, None)
        t_val = getattr(tg_pref, field, None)
        if w_val is None or w_val == "":
            if t_val is not None:
                setattr(web_pref, field, t_val)
        elif t_val is not None and t_val != "" and w_val != t_val:
            if prefer_tg:
                setattr(web_pref, field, t_val)

    # Interests
    w_interests = list(web_pref.interests or [])
    t_interests = list(tg_pref.interests or [])
    for item in t_interests:
        if item not in w_interests:
            w_interests.append(item)
    web_pref.interests = w_interests

    # Sources
    w_sources = dict(web_pref.sources or {})
    t_sources = dict(tg_pref.sources or {})
    for k, v in t_sources.items():
        if k not in w_sources or prefer_tg:
            w_sources[k] = v
    web_pref.sources = w_sources

    # Delete synthetic preference so uq_preference_member is not violated
    db.delete(tg_pref)
    db.flush()


def merge_synthetic_user(db: Session, web_user: User, synthetic_user: User) -> None:
    """Merges synthetic_user into web_user completely and deletes synthetic_user:
    1. Iterates over a copy list of synthetic_user's memberships.
    2. Merges duplicate memberships and preferences.
    3. Re-points all discovered foreign keys referencing users.id to web_user.id.
    4. Asserts 0 foreign key references to synthetic_user remain.
    5. Deletes synthetic_user.
    """
    syn_id = synthetic_user.id
    web_id = web_user.id

    # 1. Memberships and Preferences
    syn_memberships = list(
        db.scalars(select(TripMember).where(TripMember.user_id == syn_id)).all()
    )
    for s_mem in syn_memberships:
        trip_id = s_mem.trip_id
        w_mem = db.scalar(
            select(TripMember).where(TripMember.trip_id == trip_id, TripMember.user_id == web_id)
        )
        if w_mem:
            # Both were members of this trip
            if not w_mem.telegram_user_id and s_mem.telegram_user_id:
                w_mem.telegram_user_id = s_mem.telegram_user_id
            if not w_mem.telegram_username and s_mem.telegram_username:
                w_mem.telegram_username = s_mem.telegram_username

            w_pref = db.scalar(
                select(Preference).where(Preference.trip_id == trip_id, Preference.user_id == web_id)
            )
            s_pref = db.scalar(
                select(Preference).where(Preference.trip_id == trip_id, Preference.user_id == syn_id)
            )
            if w_pref and s_pref:
                merge_preferences(db, w_pref, s_pref)
            elif s_pref and not w_pref:
                s_pref.user_id = web_id
                db.flush()

            db.delete(s_mem)
            db.flush()
        else:
            # Only synthetic user was in this trip
            s_mem.user_id = web_id
            s_pref = db.scalar(
                select(Preference).where(Preference.trip_id == trip_id, Preference.user_id == syn_id)
            )
            if s_pref:
                s_pref.user_id = web_id
            db.flush()

    # 2. Check any remaining preferences owned by synthetic user
    remaining_syn_prefs = list(
        db.scalars(select(Preference).where(Preference.user_id == syn_id)).all()
    )
    for s_pref in remaining_syn_prefs:
        w_pref = db.scalar(
            select(Preference).where(Preference.trip_id == s_pref.trip_id, Preference.user_id == web_id)
        )
        if w_pref:
            merge_preferences(db, w_pref, s_pref)
        else:
            s_pref.user_id = web_id
            db.flush()

    # 3. Re-point all other tables discovered dynamically
    ref_cols = get_user_referencing_columns(db.get_bind())
    for tbl, col in ref_cols:
        if tbl in ("users", "trip_members", "preferences"):
            continue
        db.execute(
            sa.text(f"UPDATE {tbl} SET {col} = :web_id WHERE {col} = :syn_id"),
            {"web_id": web_id, "syn_id": syn_id},
        )
        db.flush()

    # 4. Clear telegram_user_id on synthetic user before web user gets it
    if hasattr(synthetic_user, "telegram_user_id"):
        synthetic_user.telegram_user_id = None
        db.flush()

    # 5. Assert 0 references remain to synthetic user
    for tbl, col in ref_cols:
        cnt = db.scalar(
            sa.text(f"SELECT count(*) FROM {tbl} WHERE {col} = :syn_id"),
            {"syn_id": syn_id},
        )
        if cnt and cnt > 0:
            db.rollback()
            raise RuntimeError(
                f"Integrity check failed: {cnt} row(s) in {tbl}.{col} still reference synthetic user {syn_id}."
            )

    # 5. Safe to delete synthetic user
    db.delete(synthetic_user)
    db.flush()


def link_telegram_account(
    db: Session,
    code_str: str,
    tg_user_id: int,
    tg_username: Optional[str] = None,
    tg_full_name: Optional[str] = None,
) -> Tuple[bool, str, Optional[User]]:
    """Links a Telegram identity to a web User account using a one-time code."""
    clean_code = code_str.strip().upper()
    if not clean_code:
        return False, "⚠️ Please provide a valid code:\n<code>/link YOUR_CODE</code>", None

    if is_rate_limited(tg_user_id):
        return (
            False,
            "⚠️ Too many failed attempts. Please wait 15 minutes before trying again.",
            None,
        )

    # Find active codes
    now = utcnow()
    active_codes = db.scalars(
        select(TelegramLinkCode).where(
            TelegramLinkCode.used_at.is_(None),
            TelegramLinkCode.expires_at > now,
        )
    ).all()

    matched_code_record: Optional[TelegramLinkCode] = None
    for rec in active_codes:
        if hmac.compare_digest(rec.code.upper(), clean_code):
            matched_code_record = rec
            break

    if not matched_code_record:
        record_failed_attempt(tg_user_id)
        return (
            False,
            "❌ Invalid or expired link code. Please generate a fresh code in your web Profile.",
            None,
        )

    web_user = db.get(User, matched_code_record.user_id)
    if not web_user:
        record_failed_attempt(tg_user_id)
        return False, "❌ Associated web account not found.", None

    # Check 1: Web user already linked to a DIFFERENT telegram ID
    if web_user.telegram_user_id and web_user.telegram_user_id != tg_user_id:
        return (
            False,
            f"⚠️ Your web account is already linked to another Telegram account (ID: {web_user.telegram_user_id}). "
            "Please disconnect it from your web Profile first.",
            None,
        )

    # Check 2: This Telegram user is already linked to a DIFFERENT web user
    existing_linked = db.scalar(
        select(User).where(User.telegram_user_id == tg_user_id)
    )
    if existing_linked and existing_linked.id != web_user.id:
        return (
            False,
            f"⚠️ This Telegram account is already linked to web user '{existing_linked.name}'. "
            "Please disconnect that account before linking to a different one.",
            None,
        )

    # Check 3: Already linked to the same user (idempotent no-op)
    if web_user.telegram_user_id == tg_user_id:
        matched_code_record.used_at = now
        db.commit()
        clear_failed_attempts(tg_user_id)
        return (
            True,
            f"ℹ️ Your Telegram account is already linked to {web_user.name} ({web_user.email}).",
            web_user,
        )

    # Check if a synthetic user exists for this telegram user
    syn_email = f"tg_{tg_user_id}@telegram.user"
    synthetic_user = db.scalar(select(User).where(User.email == syn_email))

    try:
        if synthetic_user and synthetic_user.id != web_user.id:
            merge_synthetic_user(db, web_user, synthetic_user)

        # Assign telegram identity to web_user
        web_user.telegram_user_id = tg_user_id
        if tg_username:
            web_user.telegram_username = tg_username
        elif tg_full_name and not web_user.telegram_username:
            web_user.telegram_username = tg_full_name

        matched_code_record.used_at = now
        db.commit()
        db.refresh(web_user)
        clear_failed_attempts(tg_user_id)
    except Exception as exc:
        db.rollback()
        log.error("Failed to link telegram user %s to user %s: %s", tg_user_id, web_user.id, exc, exc_info=True)
        return False, f"❌ Failed to link accounts: {str(exc)}", None

    return (
        True,
        f"🎉 <b>Successfully linked!</b>\n\n"
        f"Your Telegram account is now connected to <b>{web_user.name}</b> (<code>{web_user.email}</code>).\n"
        f"All your trip preferences and messages are unified across Web and Telegram.",
        web_user,
    )


def unlink_telegram_account(db: Session, user: User) -> None:
    """Disconnects a Telegram identity from a web user."""
    user.telegram_user_id = None
    user.telegram_username = None
    db.commit()
    db.refresh(user)
