"""Who is in a project, with which role: members, role changes and invitations."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update

from studio import audit
from studio.auth import CurrentUser
from studio.config import get_settings
from studio.db import Db
from studio.models import Invitation, Project, ProjectMember, User
from studio.permissions import (
    Permission,
    Role,
    allows,
    authorize,
    can_change_role,
    deny,
    role_in,
)
from studio.ratelimit import limiter
from studio.routes.projects import ProjectOut, get_project
from studio.security import hash_token, new_token

router = APIRouter(prefix="/api", tags=["members"])

INVITATION_LIFETIME = timedelta(days=7)


class MemberOut(BaseModel):
    user_id: str
    display_name: str
    email: str | None  # only for people who manage members
    role: Role
    added_at: datetime


class RoleChange(BaseModel):
    role: Role


class InvitationIn(BaseModel):
    email: str = Field(max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    role: Literal[Role.ADMIN, Role.EDITOR, Role.VIEWER]  # ownership is given, not invited


class InvitationOut(BaseModel):
    id: str
    email: str
    role: Role
    created_at: datetime
    expires_at: datetime

    @classmethod
    def of(cls, i: Invitation) -> "InvitationOut":
        return cls(
            id=str(i.id),
            email=i.email,
            role=i.role,
            created_at=i.created_at,
            expires_at=i.expires_at,
        )


class InvitationCreated(InvitationOut):
    link: str  # holds the token: shown this once, never stored


class AcceptRequest(BaseModel):
    token: str = Field(min_length=20, max_length=100)


def lock_project(
    db: Db, user: User, project_id: uuid.UUID, permission: Permission
) -> tuple[Project, Role]:
    """The project, locked until this transaction ends, and the user's role in it.

    Membership changes in one project happen one at a time, so two owners can't
    both step down at the same moment and leave the project without an owner.
    """
    project = get_project(db, user, project_id, permission)
    db.refresh(project, with_for_update=True)  # waits here for any other change to finish
    return project, authorize(db, user, project, permission)  # roles may have just changed


def get_member(db: Db, project_id: uuid.UUID, user_id: uuid.UUID) -> ProjectMember:
    member = db.get(ProjectMember, (project_id, user_id))
    if member is None:
        raise HTTPException(404, "not a member of this project")
    return member


def owner_count(db: Db, project_id: uuid.UUID) -> int:
    return db.scalar(
        select(func.count()).where(
            ProjectMember.project_id == project_id, ProjectMember.role == Role.OWNER
        )
    )


def member_target(member: ProjectMember) -> audit.Target:
    return audit.Target("user", member.user_id, member.user.display_name, member.project_id)


@router.get("/projects/{project_id}/members")
def list_members(project_id: uuid.UUID, db: Db, user: CurrentUser) -> list[MemberOut]:
    get_project(db, user, project_id)
    show_email = allows(role_in(db, user, project_id), Permission.MANAGE_MEMBERS)
    members = db.scalars(
        select(ProjectMember)
        .join(User, User.id == ProjectMember.user_id)
        .where(ProjectMember.project_id == project_id)
        .order_by(User.display_name)
    )
    return [
        MemberOut(
            user_id=str(m.user_id),
            display_name=m.user.display_name,
            email=m.user.email if show_email else None,
            role=m.role,
            added_at=m.created_at,
        )
        for m in members
    ]


@router.patch("/projects/{project_id}/members/{user_id}")
def change_role(
    project_id: uuid.UUID, user_id: uuid.UUID, body: RoleChange, db: Db, user: CurrentUser
) -> MemberOut:
    project, my_role = lock_project(db, user, project_id, Permission.MANAGE_MEMBERS)
    member = get_member(db, project_id, user_id)
    old = Role(member.role)
    if not can_change_role(my_role, old, body.role):
        deny(
            user, member_target(member), "change_owner", my_role, "only owners can change ownership"
        )
    if old == Role.OWNER and body.role != Role.OWNER and owner_count(db, project.id) == 1:
        raise HTTPException(409, "a project needs at least one owner")
    member.role = body.role
    audit.record(
        db,
        "member.role_change",
        user,
        target=member_target(member),
        details={"from": old.value, "to": body.role.value},
    )
    return MemberOut(
        user_id=str(member.user_id),
        display_name=member.user.display_name,
        email=member.user.email,
        role=member.role,
        added_at=member.created_at,
    )


@router.delete("/projects/{project_id}/members/{user_id}", status_code=204)
def remove_member(project_id: uuid.UUID, user_id: uuid.UUID, db: Db, user: CurrentUser) -> None:
    """Removes someone, or (with your own id) leaves the project."""
    leaving = user_id == user.id
    needed = Permission.VIEW if leaving else Permission.MANAGE_MEMBERS
    project, my_role = lock_project(db, user, project_id, needed)
    member = get_member(db, project_id, user_id)
    if not leaving and member.role == Role.OWNER and my_role != Role.OWNER:
        deny(user, member_target(member), "change_owner", my_role, "only owners can remove owners")
    if member.role == Role.OWNER and owner_count(db, project.id) == 1:
        raise HTTPException(409, "a project needs at least one owner")
    audit.record(
        db, "member.leave" if leaving else "member.remove", user, target=member_target(member)
    )
    db.delete(member)


@router.get("/projects/{project_id}/invitations")
def list_invitations(project_id: uuid.UUID, db: Db, user: CurrentUser) -> list[InvitationOut]:
    """Invitations that can still be accepted."""
    get_project(db, user, project_id, Permission.MANAGE_MEMBERS)
    rows = db.scalars(
        select(Invitation)
        .where(
            Invitation.project_id == project_id,
            Invitation.accepted_at.is_(None),
            Invitation.revoked_at.is_(None),
            Invitation.expires_at > func.now(),
        )
        .order_by(Invitation.created_at.desc())
    )
    return [InvitationOut.of(i) for i in rows]


@router.post("/projects/{project_id}/invitations", status_code=201)
def invite(
    project_id: uuid.UUID, body: InvitationIn, db: Db, user: CurrentUser
) -> InvitationCreated:
    limiter.check(f"invite:{user.id}", limit=20, window=3600)
    project, _ = lock_project(db, user, project_id, Permission.MANAGE_MEMBERS)
    email = body.email.strip().lower()
    member = db.scalar(
        select(ProjectMember.user_id)
        .join(User, User.id == ProjectMember.user_id)
        .where(ProjectMember.project_id == project.id, User.email == email)
    )
    if member:
        raise HTTPException(409, "already a member of this project")
    now = datetime.now(UTC)
    # A new invitation replaces any open one for the same address.
    db.execute(
        update(Invitation)
        .where(
            Invitation.project_id == project.id,
            Invitation.email == email,
            Invitation.accepted_at.is_(None),
            Invitation.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    token = new_token()
    invitation = Invitation(
        project_id=project.id,
        email=email,
        role=body.role,
        token_hash=hash_token(token),
        invited_by=user.id,
        expires_at=now + INVITATION_LIFETIME,
    )
    db.add(invitation)
    db.flush()
    db.refresh(invitation)
    audit.record(
        db,
        "invitation.create",
        user,
        target=audit.Target("invitation", invitation.id, email, project.id),
        details={"email": email, "role": body.role.value},
    )
    # The token travels in the #fragment: browsers never send that part to a server.
    link = f"{get_settings().app_url}/invite#{token}"
    return InvitationCreated(**InvitationOut.of(invitation).model_dump(), link=link)


@router.delete("/projects/{project_id}/invitations/{invitation_id}", status_code=204)
def revoke_invitation(
    project_id: uuid.UUID, invitation_id: uuid.UUID, db: Db, user: CurrentUser
) -> None:
    project, _ = lock_project(db, user, project_id, Permission.MANAGE_MEMBERS)
    invitation = db.get(Invitation, invitation_id)
    if invitation is None or invitation.project_id != project.id:
        raise HTTPException(404, "invitation not found")
    if invitation.accepted_at is None and invitation.revoked_at is None:
        invitation.revoked_at = datetime.now(UTC)
        audit.record(
            db,
            "invitation.revoke",
            user,
            target=audit.Target("invitation", invitation.id, invitation.email, project.id),
        )


def why_invalid(
    invitation: Invitation | None, project: Project | None, user: User, now: datetime
) -> str | None:
    if invitation is None or project is None:
        return "unknown link"
    if invitation.revoked_at:
        return "revoked"
    if invitation.accepted_at:
        return "already used"
    if invitation.expires_at <= now:
        return "expired"
    if project.org_id != user.org_id:
        return "another organization"
    if invitation.email != user.email.lower():
        return "another email address"
    return None


@router.post("/invitations/accept")
def accept_invitation(body: AcceptRequest, db: Db, user: CurrentUser) -> ProjectOut:
    limiter.check(f"accept:{user.id}", limit=10, window=600)
    now = datetime.now(UTC)
    # FOR UPDATE: if the same link is accepted twice at once, the second waits and
    # then finds it already used.
    invitation = db.scalar(
        select(Invitation).where(Invitation.token_hash == hash_token(body.token)).with_for_update()
    )
    project = db.get(Project, invitation.project_id) if invitation else None
    problem = why_invalid(invitation, project, user, now)
    if problem:
        audit.record_now(
            "invitation.accept",
            user,
            target=audit.Target("invitation", invitation.id, invitation.email, project.id)
            if invitation and project.org_id == user.org_id
            else None,
            details={"reason": problem},
        )
        # One answer for every case: the response says nothing about other people's links.
        raise HTTPException(404, "this invitation link is not valid for your account")
    if role_in(db, user, project.id):
        raise HTTPException(409, "you are already a member of this project")
    invitation.accepted_at, invitation.accepted_by = now, user.id
    db.add(
        ProjectMember(
            project_id=project.id,
            user_id=user.id,
            org_id=user.org_id,
            role=invitation.role,
            added_by=invitation.invited_by,
        )
    )
    audit.record(
        db,
        "invitation.accept",
        user,
        target=audit.Target.of(project),
        details={"role": invitation.role},
    )
    return ProjectOut.of(project, Role(invitation.role))
