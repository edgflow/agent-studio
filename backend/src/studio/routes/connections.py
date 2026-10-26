"""OAuth connections: connect an account, check it, disconnect it.

Connecting is the authorization code flow with PKCE:

1. POST /start stores a random `state` (hashed) and a PKCE verifier, and returns
   the provider's authorization URL. The browser goes there.
2. The person approves at the provider, which sends the browser back to our fixed
   callback URL with `code` and `state`.
3. The callback checks the state (same user, not expired, single use), trades the
   code and verifier for a token, asks the provider whose account it is, and only
   then stores the token, encrypted.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Cookie, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import delete, select

from studio import audit, crypto, providers
from studio.auth import CurrentUser, user_for_token
from studio.config import get_settings
from studio.db import Db
from studio.models import Connection, OAuthState, Project, User
from studio.permissions import Permission, authorize
from studio.ratelimit import limiter
from studio.routes.projects import get_project
from studio.security import hash_token, new_token

router = APIRouter(prefix="/api", tags=["connections"])

STATE_LIFETIME = timedelta(minutes=10)


class ProviderOut(BaseModel):
    name: str
    label: str
    configured: bool
    scopes: list[str]


class ConnectionOut(BaseModel):
    """What the UI may know about a connection. Never the token."""

    id: str
    provider: str
    provider_label: str
    owner: Literal["personal", "project"]
    project_id: str | None
    account_login: str
    scopes: list[str]
    status: str
    created_at: datetime
    expires_at: datetime | None
    last_checked_at: datetime | None

    @classmethod
    def of(cls, c: Connection) -> "ConnectionOut":
        return cls(
            id=str(c.id),
            provider=c.provider,
            provider_label=providers.LABELS.get(c.provider, c.provider),
            owner="personal" if c.user_id else "project",
            project_id=str(c.project_id) if c.project_id else None,
            account_login=c.account_login,
            scopes=c.scopes,
            status=c.status,
            created_at=c.created_at,
            expires_at=c.expires_at,
            last_checked_at=c.last_checked_at,
        )


class StartRequest(BaseModel):
    project_id: uuid.UUID | None = None  # set: a connection shared with this project


class StartOut(BaseModel):
    authorize_url: str


class DisconnectOut(BaseModel):
    revoked_at_provider: bool
    message: str


def target(c: Connection) -> audit.Target:
    return audit.Target("connection", c.id, f"{c.provider}: {c.account_login}", c.project_id)


def get_connection(db: Db, user: User, connection_id: uuid.UUID, manage: bool) -> Connection:
    """A personal connection of the user's own, or a shared connection of one of their
    projects (members may look; managing needs the manage_connections permission)."""
    c = db.get(Connection, connection_id)
    if c is None or c.org_id != user.org_id or (c.user_id and c.user_id != user.id):
        raise HTTPException(404, "connection not found")
    if c.project_id:
        permission = Permission.MANAGE_CONNECTIONS if manage else Permission.VIEW
        project = db.get(Project, c.project_id)
        authorize(db, user, project, permission, target(c), not_found="connection not found")
    return c


def provider_or_404(name: str) -> providers.Provider:
    found = providers.configured().get(name)
    if found is None:
        raise HTTPException(404, f"{name} is not set up on this server")
    return found


@router.get("/connections/providers")
def list_providers(user: CurrentUser) -> list[ProviderOut]:
    ready = providers.configured() if crypto.configured() else {}
    return [
        ProviderOut(
            name=name,
            label=label,
            configured=name in ready,
            scopes=list(ready[name].scopes) if name in ready else [],
        )
        for name, label in providers.LABELS.items()
    ]


@router.get("/connections")
def list_personal(db: Db, user: CurrentUser) -> list[ConnectionOut]:
    rows = db.scalars(
        select(Connection).where(Connection.user_id == user.id).order_by(Connection.provider)
    )
    return [ConnectionOut.of(c) for c in rows]


@router.get("/projects/{project_id}/connections")
def list_shared(project_id: uuid.UUID, db: Db, user: CurrentUser) -> list[ConnectionOut]:
    get_project(db, user, project_id)
    rows = db.scalars(
        select(Connection).where(Connection.project_id == project_id).order_by(Connection.provider)
    )
    return [ConnectionOut.of(c) for c in rows]


@router.post("/connections/{provider}/start")
def start(provider: str, body: StartRequest, db: Db, user: CurrentUser) -> StartOut:
    limiter.check(f"oauth-start:{user.id}", limit=20, window=3600)
    p = provider_or_404(provider)
    if not crypto.configured():
        raise HTTPException(503, "token encryption is not configured on this server")
    if body.project_id:
        get_project(db, user, body.project_id, Permission.MANAGE_CONNECTIONS)
    now = datetime.now(UTC)
    db.execute(delete(OAuthState).where(OAuthState.expires_at < now))  # abandoned attempts
    state = new_token()
    verifier, challenge = providers.pkce_pair()
    db.add(
        OAuthState(
            state_hash=hash_token(state),
            user_id=user.id,
            provider=p.name,
            project_id=body.project_id,
            code_verifier=crypto.encrypt(verifier),
            expires_at=now + STATE_LIFETIME,
        )
    )
    return StartOut(authorize_url=providers.authorize_url(p, state, challenge))


def back_to_app(**query: str) -> RedirectResponse:
    """Always the same page of our own app: the callback never redirects anywhere else."""
    params = "&".join(f"{k}={v}" for k, v in query.items())
    return RedirectResponse(f"{get_settings().app_url}/connections?{params}", status_code=303)


@router.get("/connections/{provider}/callback")
def callback(
    provider: str,
    db: Db,
    state: str = "",
    code: str = "",
    error: str = "",
    studio_session: Annotated[str | None, Cookie()] = None,
) -> RedirectResponse:
    """Where the provider sends the browser back. Every outcome is a redirect to the
    connections page; only these fixed error codes ever reach the URL."""
    user = user_for_token(db, studio_session)
    if user is None:
        return back_to_app(error="signed_out")
    pending = db.get(OAuthState, hash_token(state)) if state else None
    if pending:
        db.delete(pending)  # single use, whatever happens next
        db.commit()

    def fail(reason: str, code_for_url: str) -> RedirectResponse:
        audit.record_now(
            "connection.create",
            user,
            outcome="failure",
            details={"provider": provider, "reason": reason},
        )
        return back_to_app(error=code_for_url)

    # The state must be one we issued, to this user, for this provider, not long ago.
    if pending is None or pending.user_id != user.id or pending.provider != provider:
        return fail("unknown state", "invalid_state")
    if pending.expires_at <= datetime.now(UTC):
        return fail("state expired", "expired")
    if error:
        return fail("declined at the provider", "cancelled")
    p = providers.configured().get(provider)
    if p is None or not code:
        return fail("no code", "invalid_state")
    if pending.project_id:  # roles may have changed while the person was at the provider
        project = db.get(Project, pending.project_id)
        if project is None:
            return fail("project gone", "not_allowed")
        try:
            authorize(db, user, project, Permission.MANAGE_CONNECTIONS)
        except HTTPException:
            return fail("not allowed", "not_allowed")

    try:
        tokens = providers.exchange_code(p, code, crypto.decrypt(pending.code_verifier))
        if not set(p.scopes) <= set(tokens.scopes):
            providers.revoke(p, tokens.access_token)  # don't keep a token we can't use
            return fail("scopes not granted", "missing_scopes")
        account = providers.whoami(p, tokens.access_token)
    except providers.ProviderError as e:
        return fail(str(e), "provider_error")

    owner = (
        Connection.project_id == pending.project_id
        if pending.project_id
        else Connection.user_id == user.id
    )
    connection = db.scalar(select(Connection).where(Connection.provider == p.name, owner))
    if connection is None:  # connecting again replaces the old token
        connection = Connection(
            org_id=user.org_id,
            provider=p.name,
            user_id=None if pending.project_id else user.id,
            project_id=pending.project_id,
        )
        db.add(connection)
    connection.account_id, connection.account_login = account.id, account.login
    connection.scopes = tokens.scopes
    connection.access_token = crypto.encrypt(tokens.access_token)
    connection.refresh_token = (
        crypto.encrypt(tokens.refresh_token) if tokens.refresh_token else None
    )
    connection.expires_at = tokens.expires_at
    connection.status, connection.created_by = "active", user.id
    connection.last_checked_at = datetime.now(UTC)
    db.flush()
    audit.record(
        db,
        "connection.create",
        user,
        target=target(connection),
        details={"provider": p.name, "account": account.login, "scopes": tokens.scopes},
    )
    return back_to_app(connected=p.name)


@router.post("/connections/{connection_id}/test")
def test_connection(connection_id: uuid.UUID, db: Db, user: CurrentUser) -> ConnectionOut:
    """Asks the provider whether the token still works, and records the answer."""
    c = get_connection(db, user, connection_id, manage=True)
    p = provider_or_404(c.provider)
    try:
        c.account_login = providers.whoami(p, crypto.decrypt(c.access_token)).login
        c.status = "active"
    except providers.TokenRejected:
        c.status = "invalid"
    except providers.ProviderError as e:
        raise HTTPException(502, str(e)) from None
    c.last_checked_at = datetime.now(UTC)
    return ConnectionOut.of(c)


@router.delete("/connections/{connection_id}")
def disconnect(connection_id: uuid.UUID, db: Db, user: CurrentUser) -> DisconnectOut:
    """Revokes the token at the provider, then deletes our copy either way."""
    c = get_connection(db, user, connection_id, manage=True)
    p = providers.configured().get(c.provider)
    revoked = p is not None and providers.revoke(p, crypto.decrypt(c.access_token))
    audit.record(
        db,
        "connection.delete",
        user,
        target=target(c),
        outcome="success" if revoked else "failure",
        details={"provider": c.provider, "revoked_at_provider": revoked},
    )
    db.delete(c)
    label = providers.LABELS.get(c.provider, c.provider)
    return DisconnectOut(
        revoked_at_provider=revoked,
        message="Disconnected, and the token is revoked."
        if revoked
        else f"Our copy of the token is deleted, but {label} didn't confirm it is revoked. "
        f"Revoke the app's access in your {label} settings too.",
    )
