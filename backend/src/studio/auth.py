"""Login with email and password; a session cookie identifies the user afterwards."""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from studio.config import get_settings
from studio.db import Db
from studio.models import AuthSession, User
from studio.security import hash_token, new_session_token, verify_password

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
def login(body: LoginRequest, response: Response, db: Db) -> UserOut:
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if not verify_password(user.password_hash if user else None, body.password):
        # The same message for an unknown email and a wrong password.
        raise HTTPException(401, "wrong email or password")
    settings = get_settings()
    token = new_session_token()
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
    return UserOut.of(user)


@router.post("/logout", status_code=204)
def logout(
    response: Response, db: Db, studio_session: Annotated[str | None, Cookie()] = None
) -> None:
    if studio_session:
        db.execute(delete(AuthSession).where(AuthSession.token_hash == hash_token(studio_session)))
    response.delete_cookie(COOKIE, path="/")


@router.get("/me")
def me(user: CurrentUser) -> UserOut:
    return UserOut.of(user)
