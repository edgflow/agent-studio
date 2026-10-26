"""The live channel of a workflow: a WebSocket that carries presence and save notices."""

import asyncio
import json
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool

from studio.auth import COOKIE, user_for_token
from studio.config import get_settings
from studio.db import SessionLocal
from studio.live import Peer, hub
from studio.models import Project, Workflow
from studio.permissions import Permission, allows, role_in

router = APIRouter(tags=["live"])

RECHECK_SECONDS = 30  # how soon someone removed from the project loses the channel
MAX_MESSAGE = 1024


def access(workflow_id: uuid.UUID, token: str | None) -> tuple[uuid.UUID, str, bool] | None:
    """(user id, display name, may edit) for a member of the workflow's project, else None."""
    with SessionLocal() as db:
        user = user_for_token(db, token)
        workflow = db.get(Workflow, workflow_id) if user else None
        project = db.get(Project, workflow.project_id) if workflow else None
        if project is None or project.org_id != user.org_id:
            return None
        role = role_in(db, user, project.id)
        if role is None:
            return None
        return user.id, user.display_name, allows(role, Permission.EDIT)


@router.websocket("/api/workflows/{workflow_id}/live")
async def live(websocket: WebSocket, workflow_id: uuid.UUID) -> None:
    # Browsers send cookies with WebSocket handshakes from any page, and CORS doesn't
    # apply to WebSockets. Without this check, any site could open this channel as you.
    if websocket.headers.get("origin") not in get_settings().allowed_origins:
        await websocket.close(code=4403)
        return
    token = websocket.cookies.get(COOKIE)
    found = await run_in_threadpool(access, workflow_id, token)
    if found is None:
        await websocket.close(code=4404)  # not signed in, or not a member: nothing to see
        return
    user_id, name, can_edit = found
    await websocket.accept()
    peer = Peer(websocket, user_id, name, can_edit)
    if not hub.join(workflow_id, peer):
        await websocket.close(code=4429)
        return
    try:
        await hub.announce(workflow_id)
        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=RECHECK_SECONDS)
            except TimeoutError:
                # Roles change: keep checking that this person may still be here.
                if await run_in_threadpool(access, workflow_id, token) is None:
                    await websocket.close(code=4404)
                    return
                continue
            if len(raw) > MAX_MESSAGE or not peer.within_rate():
                await websocket.close(code=4429)
                return
            try:
                message = json.loads(raw)
            except ValueError:
                continue
            if isinstance(message, dict) and message.get("type") == "editing":
                # Viewers can't edit, so they never show up as editing.
                peer.editing = bool(message.get("editing")) and peer.can_edit
                await hub.announce(workflow_id)
    except WebSocketDisconnect:
        pass
    finally:
        hub.leave(workflow_id, peer)
        await hub.announce(workflow_id)
