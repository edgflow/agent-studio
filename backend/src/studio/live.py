"""Live presence: who has a workflow open, who has unsaved changes, and who just saved.

Presence is a hint for people, not a lock: saving still goes through the revision
check, which stays the only thing that decides whether a save wins.

Limits of this design, on purpose:
- The hub lives in this process's memory. With several workers or servers, each
  sees only its own sockets: put a broker (Redis pub/sub, Postgres LISTEN/NOTIFY)
  between them before scaling out.
- Nothing here is stored or audited. It is gone when the last person leaves.
- People are shown by display name and initials, never by email or id.
"""

import hashlib
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket

MAX_PEOPLE_PER_WORKFLOW = 50
MAX_TABS_PER_PERSON = 5
MAX_MESSAGES = 30  # from one socket within...
PER_SECONDS = 10


@dataclass(eq=False)  # each tab is its own peer, compared by identity
class Peer:
    socket: WebSocket
    user_id: uuid.UUID
    name: str
    can_edit: bool
    editing: bool = False
    _sent: deque[float] = field(default_factory=deque)

    def within_rate(self) -> bool:
        """False when this socket sends more than MAX_MESSAGES in PER_SECONDS."""
        now = time.monotonic()
        while self._sent and self._sent[0] <= now - PER_SECONDS:
            self._sent.popleft()
        self._sent.append(now)
        return len(self._sent) <= MAX_MESSAGES


def initials(name: str) -> str:
    return "".join(word[0] for word in name.split()[:2]).upper() or "?"


def hue(user_id: uuid.UUID) -> int:
    """A colour that stays the same for a person, without revealing who they are."""
    return int(hashlib.sha256(user_id.bytes).hexdigest()[:4], 16) % 360


class Hub:
    """The open sockets of every workflow, grouped by workflow.

    Everything runs on the one event loop, and nothing awaits between reading and
    changing `rooms`, so no lock is needed.
    """

    def __init__(self) -> None:
        self.rooms: dict[uuid.UUID, list[Peer]] = defaultdict(list)

    def join(self, workflow_id: uuid.UUID, peer: Peer) -> bool:
        room = self.rooms[workflow_id]
        people = {p.user_id for p in room} | {peer.user_id}
        tabs = sum(1 for p in room if p.user_id == peer.user_id)
        if len(people) > MAX_PEOPLE_PER_WORKFLOW or tabs >= MAX_TABS_PER_PERSON:
            return False
        room.append(peer)
        return True

    def leave(self, workflow_id: uuid.UUID, peer: Peer) -> None:
        room = self.rooms.get(workflow_id, [])
        if peer in room:
            room.remove(peer)
        if not room:
            self.rooms.pop(workflow_id, None)

    def people(self, workflow_id: uuid.UUID) -> list[dict[str, Any]]:
        """One entry per person, however many tabs they have open."""
        by_user: dict[uuid.UUID, dict[str, Any]] = {}
        for p in self.rooms.get(workflow_id, []):
            entry = by_user.setdefault(
                p.user_id,
                {
                    "name": p.name,
                    "initials": initials(p.name),
                    "hue": hue(p.user_id),
                    "editing": False,
                },
            )
            entry["editing"] = entry["editing"] or p.editing
        return [{"user": user, **entry} for user, entry in by_user.items()]

    async def announce(self, workflow_id: uuid.UUID) -> None:
        """Sends everyone in the workflow the current list of people."""
        people = self.people(workflow_id)
        for peer in list(self.rooms.get(workflow_id, [])):
            await self._send(
                peer,
                {
                    "type": "presence",
                    "people": [
                        {k: v for k, v in p.items() if k != "user"}
                        | {"you": p["user"] == peer.user_id}
                        for p in people
                    ],
                },
            )

    async def saved(self, workflow_id: uuid.UUID, revision: int, by: str) -> None:
        """Called after a save is committed: everyone with the workflow open hears about it."""
        await self.broadcast(workflow_id, {"type": "saved", "revision": revision, "by": by})

    async def deleted(self, workflow_id: uuid.UUID, by: str) -> None:
        await self.broadcast(workflow_id, {"type": "deleted", "by": by})

    async def broadcast(self, workflow_id: uuid.UUID, message: dict[str, Any]) -> None:
        for peer in list(self.rooms.get(workflow_id, [])):
            await self._send(peer, message)

    @staticmethod
    async def _send(peer: Peer, message: dict[str, Any]) -> None:
        try:
            await peer.socket.send_json(message)
        except Exception:
            pass  # the socket is closing; its own handler removes it from the room


hub = Hub()
