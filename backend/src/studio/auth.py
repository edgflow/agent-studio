"""Login with email and password; a session cookie identifies the user afterwards."""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from studio import audit
from studio.config import get_settings
from studio.db import Db
from studio.models import AuthSession, User
from studio.ratelimit import limiter
from studio.security import hash_token, new_token, verify_password

COOKIE = "studio_session"
router = APIRouter(prefix="/api/auth", tags=["auth"])


def user_for_token(db: Session, token: str | None) -> User | None:
    if not token:
        return None
    session = db.get(AuthSession, hash_token(token))
    if session is None or session.expires_at <= datetime.now(UTC):
        return None
    return session.user


def current_user(
    db: Db,
    studio_session: Annotated[str | None, Cookie()] = None,
) -> User:
    user = user_for_token(db, studio_session)
    if user is None:
        raise HTTPException(401, "not signed in")
    return user


CurrentUser = Annotated[User, Depends(current_user)]


class LoginRequest(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=200)


class UserOut(BaseModel):
    id: str
    email: str
    display_name: str
    is_org_admin: bool

    @classmethod
    def of(cls, user: User) -> "UserOut":
        return cls(
            id=str(user.id),
            email=user.email,
            display_name=user.display_name,
            is_org_admin=user.is_org_admin,
        )


@router.post("/login")
def login(body: LoginRequest, request: Request, response: Response, db: Db) -> UserOut:
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    # Sign-ins are the one place an IP address earns its keep: spotting password guessing.
    ip = request.client.host if request.client else None
    # Slow down password guessing: per address and account, and per address overall.
    limiter.check(f"login:{ip}:{body.email.lower()}", limit=10, window=15 * 60)
    limiter.check(f"login:{ip}", limit=100, window=15 * 60)
    if not verify_password(user.password_hash if user else None, body.password):
        # Filed under the account that was tried. Never the password, and never the typed
        # email of an unknown account: people sometimes type their password into that field.
        audit.record_now(
            "auth.login",
            None,
            target=audit.Target.of(user) if user else None,
            org_id=user.org_id if user else None,
            details={"reason": "wrong password" if user else "unknown account"},
            source_ip=ip,
        )
        # The same message for an unknown email and a wrong password.
        raise HTTPException(401, "wrong email or password")
    settings = get_settings()
    token = new_token()
    db.add(
        AuthSession(
            token_hash=hash_token(token),
            user_id=user.id,
            expires_at=datetime.now(UTC) + timedelta(hours=settings.session_hours),
        )
    )
    response.set_cookie(
        COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=settings.session_hours * 3600,
        path="/",
    )
    audit.record(db, "auth.login", user, target=audit.Target.of(user), source_ip=ip)
    return UserOut.of(user)


@router.post("/logout", status_code=204)
def logout(
    response: Response, db: Db, studio_session: Annotated[str | None, Cookie()] = None
) -> None:
    if studio_session:
        user = user_for_token(db, studio_session)
        db.execute(delete(AuthSession).where(AuthSession.token_hash == hash_token(studio_session)))
        if user:
            audit.record(db, "auth.logout", user, target=audit.Target.of(user))
    response.delete_cookie(COOKIE, path="/")


@router.get("/me")
def me(user: CurrentUser) -> UserOut:
    return UserOut.of(user)
