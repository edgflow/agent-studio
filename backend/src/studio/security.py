"""Passwords, session tokens and the CSRF guard."""

import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import HTTPException, Request

_hasher = PasswordHasher()

# A hash of a random string: verifying against it costs the same as a real
# check, so an unknown email takes as long as a wrong password.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except VerifyMismatchError:
        return False


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Session tokens are stored as SHA-256: a leaked table can't be replayed."""
    return hashlib.sha256(token.encode()).hexdigest()


UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
CSRF_HEADER = "x-requested-with"


def require_csrf_header(request: Request) -> None:
    """Cookie-authenticated writes must carry a custom header.

    A cross-site form or image tag cannot set custom headers, and a
    cross-site fetch() that sets one needs a CORS preflight, which this API
    never grants. So a request with the header came from our own frontend.
    """
    if request.method in UNSAFE_METHODS and request.headers.get(CSRF_HEADER) != "studio":
        raise HTTPException(403, "missing the X-Requested-With: studio header")
