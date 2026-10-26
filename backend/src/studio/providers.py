"""OAuth providers, and the four calls we make to one.

Every provider here speaks the shape of a GitHub OAuth app: the authorization
code flow with PKCE, a token endpoint, GET /user, and token revocation at
DELETE /applications/{client_id}/token. The local test provider in devtools/
copies that shape, so the same code runs against both.
"""

import base64
import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx

from studio.config import get_settings

LABELS = {"github": "GitHub", "local": "Local test provider"}


@dataclass(frozen=True)
class Provider:
    name: str
    authorize_url: str
    token_url: str
    api_url: str
    client_id: str
    client_secret: str
    # As few as the feature needs. read:user: enough to confirm whose account it is.
    scopes: tuple[str, ...]

    @property
    def label(self) -> str:
        return LABELS[self.name]

    @property
    def redirect_uri(self) -> str:
        """Fixed, and registered with the provider. Never built from the incoming request,
        so nobody can steer the authorization code to a server of their choosing."""
        return f"{get_settings().app_url}/api/connections/{self.name}/callback"


def configured() -> dict[str, Provider]:
    """The providers this server has credentials for."""
    s = get_settings()
    found = {}
    if s.github_client_id and s.github_client_secret:
        found["github"] = Provider(
            "github",
            "https://github.com/login/oauth/authorize",
            "https://github.com/login/oauth/access_token",
            "https://api.github.com",
            s.github_client_id,
            s.github_client_secret,
            ("read:user",),
        )
    if s.dev_oauth_url and s.dev_oauth_client_secret:
        found["local"] = Provider(
            "local",
            f"{s.dev_oauth_url}/authorize",
            f"{s.dev_oauth_url}/token",
            s.dev_oauth_url,
            s.dev_oauth_client_id,
            s.dev_oauth_client_secret,
            ("read:user",),
        )
    return found


class ProviderError(Exception):
    """The provider refused, or couldn't be reached. The message is ours, not theirs."""


class TokenRejected(ProviderError):
    """The provider no longer accepts the token (revoked, expired, app uninstalled)."""


@dataclass
class Tokens:
    access_token: str
    scopes: list[str]
    refresh_token: str | None
    expires_at: datetime | None


@dataclass
class Account:
    id: str
    login: str


def http() -> httpx.Client:
    """Every call to a provider goes through here (tests swap in a local provider)."""
    return httpx.Client(
        timeout=10, headers={"Accept": "application/json", "User-Agent": "agent-studio"}
    )


def pkce_pair() -> tuple[str, str]:
    """PKCE: we keep the verifier and send only its SHA-256 (the challenge). A stolen
    authorization code is useless without the verifier, which never leaves the server."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def authorize_url(p: Provider, state: str, code_challenge: str) -> str:
    query = {
        "response_type": "code",
        "client_id": p.client_id,
        "redirect_uri": p.redirect_uri,
        "scope": " ".join(p.scopes),
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "allow_signup": "false",
    }
    return f"{p.authorize_url}?{urlencode(query)}"


def exchange_code(p: Provider, code: str, verifier: str) -> Tokens:
    """Trades the authorization code (plus the PKCE verifier) for tokens."""
    try:
        with http() as client:
            r = client.post(
                p.token_url,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": p.redirect_uri,
                    "client_id": p.client_id,
                    "client_secret": p.client_secret,
                    "code_verifier": verifier,
                },
            )
        body = r.json()
    except (httpx.HTTPError, ValueError) as e:
        raise ProviderError("the provider could not be reached") from e
    # GitHub answers errors with 200 and an "error" field, so check the body, not just the status.
    if r.status_code != 200 or "error" in body or not body.get("access_token"):
        raise ProviderError("the provider refused the authorization code")
    if str(body.get("token_type", "")).lower() != "bearer":
        raise ProviderError("unexpected token type")
    expires_in = body.get("expires_in")
    return Tokens(
        access_token=body["access_token"],
        scopes=[s for s in re.split(r"[,\s]+", body.get("scope", "")) if s],
        refresh_token=body.get("refresh_token"),
        expires_at=datetime.now(UTC) + timedelta(seconds=int(expires_in)) if expires_in else None,
    )


def whoami(p: Provider, access_token: str) -> Account:
    """The account behind a token. Proves the token works before we say "connected"."""
    try:
        with http() as client:
            r = client.get(f"{p.api_url}/user", headers={"Authorization": f"Bearer {access_token}"})
    except httpx.HTTPError as e:
        raise ProviderError("the provider could not be reached") from e
    if r.status_code == 401:
        raise TokenRejected("the provider no longer accepts this token")
    if r.status_code != 200:
        raise ProviderError("the provider could not tell us whose account this is")
    user = r.json()
    return Account(id=str(user["id"]), login=str(user["login"])[:100])


def revoke(p: Provider, access_token: str) -> bool:
    """Asks the provider to invalidate the token. True once it is certainly unusable."""
    try:
        with http() as client:
            r = client.request(
                "DELETE",
                f"{p.api_url}/applications/{p.client_id}/token",
                auth=(p.client_id, p.client_secret),
                json={"access_token": access_token},
            )
    except httpx.HTTPError:
        return False
    return r.status_code in (204, 404)  # 404: the provider already forgot it
