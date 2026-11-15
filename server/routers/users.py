from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from server.db import get_db
from server.models import AuthSession, User
from server.schemas import PasswordChange, ProfileUpdate, UserOut
from server.security import COOKIE_NAME, _token_hash, current_user, hash_password, rate_limit, verify_password

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
