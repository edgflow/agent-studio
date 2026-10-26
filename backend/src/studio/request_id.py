"""Every request gets an id: sent back as X-Request-ID and stamped on its audit events.

A user who reports "my save failed" can quote the id from their browser's network
tab, and it leads straight to the matching audit events (and, later, log lines).
"""

import re
import uuid
from contextvars import ContextVar

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

HEADER = "x-request-id"
# An id set by a trusted proxy in front of us is kept, if it looks like one.
_VALID = re.compile(r"[A-Za-z0-9._-]{8,64}")

_current: ContextVar[str | None] = ContextVar("request_id", default=None)


def current_request_id() -> str | None:
    return _current.get()


class RequestIdMiddleware:
    """Plain ASGI middleware, so the id is visible to everything the request runs:
    dependencies, the handler (even in a worker thread) and background tasks."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        incoming = Headers(scope=scope).get(HEADER, "")
        request_id = incoming if _VALID.fullmatch(incoming) else uuid.uuid4().hex

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message).append(HEADER, request_id)
            await send(message)

        token = _current.set(request_id)
        try:
            await self.app(scope, receive, send_with_id)
        finally:
            _current.reset(token)
