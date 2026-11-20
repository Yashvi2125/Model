from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from server.config import get_settings
from server.db import get_db
from server.models import AuthSession, User, utcnow
from server.schemas import PasswordChange, ProfileUpdate, TelegramLinkCodeOut, UserOut
from server.security import COOKIE_NAME, _token_hash, current_user, hash_password, rate_limit, verify_password
from server.services.account_link import generate_link_code, unlink_telegram_account

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("/me", response_model=UserOut)
def get_me(user: User = Depends(current_user)):
    return user


@router.patch("/me", response_model=UserOut)
def update_me(body: ProfileUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if body.name is not None:
        user.name = body.name.strip()
    if body.email is not None and body.email.lower() != user.email:
        email = body.email.lower()
        if db.scalar(select(User.id).where(User.email == email, User.id != user.id)):
            raise HTTPException(409, "Another account already uses this email.")
        user.email = email
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Another account already uses this email.")
    return user


@router.post("/me/password", status_code=204)
def change_password(body: PasswordChange, request: Request, user: User = Depends(current_user),
                    db: Session = Depends(get_db)):
    rate_limit(f"pw:{user.id}", 10, 600)
    if not verify_password(user.password_hash, body.current_password):
        raise HTTPException(400, "Your current password is incorrect.")
    user.password_hash = hash_password(body.new_password)
    keep = _token_hash(request.cookies.get(COOKIE_NAME, ""))
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id, AuthSession.token_hash != keep))  # sign out other devices
    db.commit()


@router.post("/me/telegram-link-code", response_model=TelegramLinkCodeOut)
def create_telegram_link_code(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rate_limit(f"tg_code:{user.id}", 10, 60)
    code = generate_link_code(db, user.id)
    settings = get_settings()
    bot_user = settings.telegram_bot_username.lstrip("@") or "Tripmate_planner_bot"
    expires_at = utcnow() + timedelta(minutes=10)
    return TelegramLinkCodeOut(code=code, expires_at=expires_at, bot_username=bot_user)


@router.delete("/me/telegram-link", response_model=UserOut)
def remove_telegram_link(user: User = Depends(current_user), db: Session = Depends(get_db)):
    unlink_telegram_account(db, user)
    return user
