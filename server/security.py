"""Password hashing, server-side sessions, CSRF origin checks and rate limiting."""
import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque
from datetime import timedelta
from typing import Optional
from urllib.parse import urlparse

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from server.config import get_settings
from server.db import get_db
from server.models import AuthSession, User, as_utc, utcnow

COOKIE_NAME = "tripmate_session"
_hasher = PasswordHasher()
_DUMMY_HASH = _hasher.hash("timing-equalisation-password")


# ---- passwords -------------------------------------------------------------
def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError, VerificationError):
        return False


def burn_password_check(password: str) -> None:
    """Spend the same time as a real check so unknown emails are not detectable by timing."""
    verify_password(_DUMMY_HASH, password)


# ---- sessions --------------------------------------------------------------
def _token_hash(token: str) -> str:
    return hmac.new(get_settings().secret_key.encode(), token.encode(), hashlib.sha256).hexdigest()


def create_session(db: Session, user: User, remember: bool, user_agent: Optional[str]) -> tuple[str, int]:
    s = get_settings()
    lifetime = timedelta(days=s.remember_me_days) if remember else timedelta(hours=s.session_hours)
    token = secrets.token_urlsafe(32)
    db.add(AuthSession(user_id=user.id, token_hash=_token_hash(token), expires_at=utcnow() + lifetime,
                       user_agent=(user_agent or "")[:255]))
    db.execute(delete(AuthSession).where(AuthSession.expires_at < utcnow()))  # opportunistic cleanup
    db.commit()
    return token, int(lifetime.total_seconds())


def set_session_cookie(response: Response, token: str, max_age: int, remember: bool) -> None:
    s = get_settings()
    samesite = "none" if s.cookie_secure else "lax"
    response.set_cookie(COOKIE_NAME, token, httponly=True, samesite=samesite, path="/",
                        secure=s.cookie_secure, max_age=max_age if remember else None)


def clear_session_cookie(response: Response) -> None:
    s = get_settings()
    samesite = "none" if s.cookie_secure else "lax"
    response.delete_cookie(COOKIE_NAME, path="/", secure=s.cookie_secure, samesite=samesite)


def user_from_token(db: Session, token: Optional[str]) -> Optional[User]:
    if not token:
        return None
    sess = db.scalar(select(AuthSession).where(AuthSession.token_hash == _token_hash(token)))
    if not sess:
        return None
    if as_utc(sess.expires_at) < utcnow():
        db.delete(sess)
        db.commit()
        return None
    user = db.get(User, sess.user_id)
    if user and (utcnow() - as_utc(sess.last_used_at)).total_seconds() > 300:
        sess.last_used_at = utcnow()
        db.commit()
    return user


def revoke_session(db: Session, token: Optional[str]) -> None:
    if token:
        db.execute(delete(AuthSession).where(AuthSession.token_hash == _token_hash(token)))
        db.commit()


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = user_from_token(db, request.cookies.get(COOKIE_NAME))
    if not user:
        raise HTTPException(401, "Your session has expired. Please log in again.")
    return user


# ---- CSRF: state-changing browser requests must come from our own origin -----
def origin_allowed(origin: Optional[str], host: Optional[str]) -> bool:
    if not origin:  # non-browser clients (curl, tests) do not send Origin; browsers always do on cross-site POSTs
        return True
    o = origin.rstrip("/")
    if o in get_settings().origins:
        return True
    return bool(host) and urlparse(o).netloc == host


# ---- tiny in-memory rate limiter (per process) -------------------------------
_hits: dict[str, deque] = defaultdict(deque)


def rate_limit(key: str, limit: int, window_seconds: int) -> None:
    now = time.monotonic()
    q = _hits[key]
    while q and now - q[0] > window_seconds:
        q.popleft()
    if len(q) >= limit:
        raise HTTPException(429, "Too many attempts. Please wait a moment and try again.")
    q.append(now)


def reset_rate_limits() -> None:
    _hits.clear()
