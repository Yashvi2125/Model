from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from server.db import get_db
from server.models import User
from server.schemas import LoginIn, RegisterIn, UserOut
from server.security import (COOKIE_NAME, burn_password_check, clear_session_cookie, create_session, current_user,
                             hash_password, rate_limit, revoke_session, set_session_cookie, verify_password)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    return fwd or (request.client.host if request.client else "unknown")


@router.post("/register", response_model=UserOut, status_code=201)
def register(body: RegisterIn, request: Request, response: Response, db: Session = Depends(get_db)):
    rate_limit(f"register:{client_ip(request)}", 20, 3600)
    email = body.email.lower()
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(409, "An account with this email already exists. Try logging in instead.")
    user = User(name=body.name, email=email, password_hash=hash_password(body.password))
    db.add(user)
    try:
        db.commit()  # the unique constraint on users.email is the real guard against races
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "An account with this email already exists. Try logging in instead.")
    token, max_age = create_session(db, user, body.remember_me, request.headers.get("user-agent"))
    set_session_cookie(response, token, max_age, body.remember_me)
    return user


@router.post("/login", response_model=UserOut)
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    email = body.email.lower()
    rate_limit(f"login:{client_ip(request)}:{email}", 10, 300)
    user = db.scalar(select(User).where(User.email == email))
    if not user:
        burn_password_check(body.password)
    if not user or not verify_password(user.password_hash, body.password):
        raise HTTPException(401, "Incorrect email or password.")
    token, max_age = create_session(db, user, body.remember_me, request.headers.get("user-agent"))
    set_session_cookie(response, token, max_age, body.remember_me)
    return user


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    revoke_session(db, request.cookies.get(COOKIE_NAME))
    clear_session_cookie(response)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user
