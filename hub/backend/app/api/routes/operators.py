"""Routes for Operators: Calkit processes on users' machines.

See docs/dev/operator-protocol.md for how these fit with the relay.
"""

import re
import secrets
import uuid
from datetime import timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import col, func, select

from app import users
from app.api.deps import (
    PAT_SELECTOR_END_CHAR_IDX,
    PAT_SELECTOR_LENGTH_BYTES,
    PAT_VERIFIER_LENGTH_BYTES,
    CurrentSession,
    CurrentUser,
    SessionDep,
    TokenDep,
)
from app.config import settings
from app.core import utcnow
from app.models import (
    Account,
    Operator,
    OperatorPublic,
    OperatorWorkspace,
    Project,
    User,
)
from app.security import (
    create_operator_grant,
    create_relay_token,
    get_operator_grant_public_key,
    hash_token_verifier,
    verify_token_verifier,
)

router = APIRouter()

TOKEN_PREFIX = "cko_"
CHECK_IN_INTERVAL_SECONDS = 60
# Missing this many check-ins in a row means the Operator is offline
OFFLINE_AFTER_MISSED_CHECK_INS = 3
# Operators in cron mode check in this often, connecting only when asked
CRON_CHECK_IN_INTERVAL_SECONDS = 300
# How long a request to connect stands before it lapses
CONNECT_REQUEST_SECONDS = 900
OPERATOR_RELAY_TOKEN_MINUTES = 10
BROWSER_RELAY_TOKEN_SECONDS = 60


def get_current_operator(session: SessionDep, token: TokenDep) -> Operator:
    """Authenticate a request made with an Operator token."""
    if not token.startswith(TOKEN_PREFIX):
        raise HTTPException(403, "Not an Operator token")
    selector = token[len(TOKEN_PREFIX) : PAT_SELECTOR_END_CHAR_IDX]
    verifier = token[PAT_SELECTOR_END_CHAR_IDX:]
    operator = session.exec(
        select(Operator).where(Operator.selector == selector)
    ).first()
    if operator is None or not verify_token_verifier(
        verifier, operator.hashed_verifier
    ):
        raise HTTPException(403, "Invalid token")
    if not operator.is_active:
        raise HTTPException(403, "Operator has been revoked")
    return operator


CurrentOperator = Annotated[Operator, Depends(get_current_operator)]


def is_online(operator: Operator) -> bool:
    """Whether it's connected to the relay, as of a recent check-in."""
    if operator.last_seen is None or not operator.connected:
        return False
    age = (utcnow() - operator.last_seen).total_seconds()
    return age < CHECK_IN_INTERVAL_SECONDS * OFFLINE_AFTER_MISSED_CHECK_INS


def is_asleep(operator: Operator) -> bool:
    """Whether it's in cron mode and still checking in, just not connected."""
    if operator.mode != "cron" or operator.last_seen is None:
        return False
    if is_online(operator):
        return False
    age = (utcnow() - operator.last_seen).total_seconds()
    return (
        age < CRON_CHECK_IN_INTERVAL_SECONDS * OFFLINE_AFTER_MISSED_CHECK_INS
    )


def connect_requested(operator: Operator) -> bool:
    """Whether its owner asked it to connect recently enough to still do so."""
    if operator.connect_requested_at is None:
        return False
    age = (utcnow() - operator.connect_requested_at).total_seconds()
    return age < CONNECT_REQUEST_SECONDS


class OperatorOut(OperatorPublic):
    """An Operator as the API returns it: its record plus its current state."""

    is_online: bool
    is_asleep: bool
    workspace_count: int


def _out(operator: Operator) -> OperatorOut:
    return OperatorOut.model_validate(
        operator,
        update=dict(
            is_online=is_online(operator),
            is_asleep=is_asleep(operator),
            workspace_count=len(operator.workspaces),
        ),
    )


class OperatorPost(BaseModel):
    """What a machine reports about itself when registering."""

    name: str | None = Field(default=None, max_length=64)
    hostname: str | None = Field(default=None, max_length=255)
    machine_id: str | None = Field(default=None, max_length=255)
    platform: str | None = Field(default=None, max_length=64)
    calkit_version: str | None = Field(default=None, max_length=64)
    hosts: list[str] = []


class OperatorRegistered(OperatorOut):
    """A newly registered Operator, with the token only returned here."""

    token: str
    # Pinned by the Operator to check the grants browsers connect with
    grant_public_key: str


@router.post("/operators")
def post_operator(
    session: SessionDep, current_user: CurrentUser, req: OperatorPost
) -> OperatorRegistered:
    """Register a machine as one of the user's Operators."""
    # Setting up the second factor that opening sessions takes proves
    # itself by email, so that address has to be the user's
    if not current_user.email_verified:
        raise HTTPException(403, "Verify your email first")
    # Names default to the hostname, suffixed until unique for the user
    base = req.name or re.sub(
        r"[^a-z0-9-]+", "-", (req.hostname or "operator").lower()
    ).strip("-")
    base = base[:56] or "operator"
    taken = set(
        session.exec(
            select(Operator.name)
            .where(Operator.user_id == current_user.id)
            .where(Operator.is_active)
        ).all()
    )
    if req.name is not None and req.name in taken:
        raise HTTPException(409, f"An Operator named '{req.name}' exists")
    name = base
    n = 2
    while name in taken:
        name = f"{base}-{n}"
        n += 1
    selector = secrets.token_hex(PAT_SELECTOR_LENGTH_BYTES)
    verifier = secrets.token_hex(PAT_VERIFIER_LENGTH_BYTES)
    operator = Operator(
        user_id=current_user.id,
        name=name,
        hostname=req.hostname,
        machine_id=req.machine_id,
        platform=req.platform,
        calkit_version=req.calkit_version,
        hosts=req.hosts or ([req.hostname] if req.hostname else []),
        selector=selector,
        hashed_verifier=hash_token_verifier(verifier),
    )
    session.add(operator)
    session.commit()
    session.refresh(operator)
    return OperatorRegistered.model_validate(
        _out(operator),
        update=dict(
            token=f"{TOKEN_PREFIX}{selector}{verifier}",
            grant_public_key=get_operator_grant_public_key(),
        ),
    )


@router.get("/operators")
def get_operators(
    session: SessionDep, current_user: CurrentUser
) -> list[OperatorOut]:
    """List the user's Operators that haven't been revoked."""
    operators = session.exec(
        select(Operator)
        .where(Operator.user_id == current_user.id)
        .where(Operator.is_active)
        .order_by(Operator.name)  # type: ignore[arg-type]
    ).all()
    return [_out(o) for o in operators]


def _get_owned_operator(
    session: SessionDep, user: User, operator_id: uuid.UUID
) -> Operator:
    operator = session.get(Operator, operator_id)
    if operator is None or operator.user_id != user.id:
        raise HTTPException(404, "Operator not found")
    if not operator.is_active:
        raise HTTPException(410, "Operator has been revoked")
    return operator


@router.delete("/operators/{operator_id}")
def delete_operator(
    session: SessionDep, current_user: CurrentUser, operator_id: uuid.UUID
) -> OperatorOut:
    """Revoke an Operator, which stops at its next check-in."""
    operator = _get_owned_operator(session, current_user, operator_id)
    # Kept rather than deleted so a revoked token can say it was revoked
    operator.is_active = False
    session.add(operator)
    session.commit()
    session.refresh(operator)
    return _out(operator)


class LastRun(BaseModel):
    """How the latest pipeline run in a workspace ended."""

    status: str = Field(max_length=16)
    started: str | None = Field(default=None, max_length=64)
    ended: str | None = Field(default=None, max_length=64)
    failed_stages: list[Annotated[str, Field(max_length=256)]] = Field(
        default=[], max_length=50
    )


class AgentInfo(BaseModel):
    """A coding agent running in a workspace, e.g., Claude Code."""

    tool: str = Field(max_length=32)
    pid: int
    started: str | None = Field(default=None, max_length=64)
    # In one of the Operator's sessions, a tmux pane, which can be attached
    # to, or another terminal, e.g., an editor's
    where: Literal["session", "tmux", "terminal"] = "terminal"
    # What it was started from, e.g., 'Code'
    app: str | None = Field(default=None, max_length=256)
    # What it was named, and what it's doing, if it says
    name: str | None = Field(default=None, max_length=256)
    status: str | None = Field(default=None, max_length=64)


class WorkspaceInfo(BaseModel):
    """A workspace as an Operator reports it at check-in."""

    path: str = Field(max_length=4096)
    kind: Literal["personal", "managed"] = "personal"
    # The project as "owner/name", if known
    project: str | None = Field(default=None, max_length=256)
    branch: str | None = Field(default=None, max_length=256)
    commit: str | None = Field(default=None, max_length=64)
    dirty: bool | None = None
    ahead: int | None = None
    behind: int | None = None
    # Whether a pipeline run is in progress there, which stages, and since
    # when, and how the latest one ended, so the hub can show it without
    # connecting
    running: bool = False
    running_stages: list[Annotated[str, Field(max_length=256)]] = Field(
        default=[], max_length=50
    )
    running_since: str | None = Field(default=None, max_length=64)
    last_run: LastRun | None = None
    # Another hub whose Operator on the same machine is using it, which
    # keeps this one out until it's done
    in_use_by: str | None = Field(default=None, max_length=2048)
    # When it last changed, e.g., a commit, a checkout, or a run ending
    last_activity: str | None = Field(default=None, max_length=64)
    agents: list[AgentInfo] = Field(default=[], max_length=20)


class CheckIn(BaseModel):
    """What an Operator reports each time it checks in."""

    calkit_version: str | None = Field(default=None, max_length=64)
    mode: Literal["service", "foreground", "cron"] | None = None
    # False when an Operator in cron mode is only asking whether to connect
    connected: bool = True
    # Whether it will restart once idle, e.g., after Calkit was upgraded
    restart_pending: bool = False
    workspaces: list[WorkspaceInfo] = Field(default=[], max_length=1000)


class CheckInResp(BaseModel):
    """Where and how an Operator connects to the relay."""

    operator_id: uuid.UUID
    name: str
    user_id: uuid.UUID
    relay_url: str
    relay_token: str
    check_in_interval: int = CHECK_IN_INTERVAL_SECONDS
    # For Operators registered before grants were signed to pin
    grant_public_key: str
    # Whether an Operator in cron mode should connect
    connect: bool = False
    # Whether to restart once idle, as its owner asked
    restart: bool = False


def _update_workspaces(
    session: SessionDep, operator: Operator, reported: list[WorkspaceInfo]
) -> None:
    """Make the Operator's stored workspaces match what it reported."""
    existing = {ws.path: ws for ws in operator.workspaces}
    now = utcnow()
    for info in reported:
        ws = existing.pop(info.path, None)
        if ws is None:
            ws = OperatorWorkspace(operator_id=operator.id, path=info.path)
        owner = name = None
        if info.project and "/" in info.project:
            owner, name = info.project.lower().split("/", 1)
        ws.kind = info.kind
        ws.owner_name = owner
        ws.project_name = name
        ws.branch = info.branch
        ws.commit = info.commit
        ws.dirty = info.dirty
        ws.ahead = info.ahead
        ws.behind = info.behind
        ws.running = info.running
        ws.run_state = info.model_dump(
            mode="json",
            include={
                "running_stages",
                "running_since",
                "last_run",
                "in_use_by",
                "last_activity",
                "agents",
            },
        )
        ws.updated = now
        session.add(ws)
    for ws in existing.values():
        session.delete(ws)


@router.post("/operators/check-in")
def post_operator_check_in(
    session: SessionDep, operator: CurrentOperator, req: CheckIn
) -> CheckInResp:
    """Record that an Operator is alive and what it has, and tell it how
    to connect.
    """
    operator.last_seen = utcnow()
    _update_workspaces(session, operator, req.workspaces)
    if req.calkit_version is not None:
        operator.calkit_version = req.calkit_version
    if req.mode is not None:
        operator.mode = req.mode
    operator.connected = req.connected
    # A request to connect is answered once it has
    if req.connected:
        operator.connect_requested_at = None
    # As is a request to restart, which stays pending until it has
    restart = operator.restart_requested
    operator.restart_requested = False
    operator.restart_pending = req.restart_pending or restart
    session.add(operator)
    session.commit()
    session.refresh(operator)
    return CheckInResp(
        operator_id=operator.id,
        name=operator.name,
        user_id=operator.user_id,
        relay_url=settings.relay_url,
        relay_token=create_relay_token(
            "operator",
            operator_id=operator.id,
            user_id=operator.user_id,
            expires_delta=timedelta(minutes=OPERATOR_RELAY_TOKEN_MINUTES),
        ),
        connect=connect_requested(operator),
        restart=restart,
        grant_public_key=get_operator_grant_public_key(),
    )


@router.post("/operators/{operator_id}/wake")
def post_operator_wake(
    session: SessionDep, current_user: CurrentUser, operator_id: uuid.UUID
) -> OperatorOut:
    """Ask an Operator in cron mode to connect at its next check-in."""
    operator = _get_owned_operator(session, current_user, operator_id)
    operator.connect_requested_at = utcnow()
    session.add(operator)
    session.commit()
    session.refresh(operator)
    return _out(operator)


@router.post("/operators/{operator_id}/restart")
def post_operator_restart(
    session: SessionDep, current_user: CurrentUser, operator_id: uuid.UUID
) -> OperatorOut:
    """Ask an Operator to restart, e.g., to run a newer Calkit, once no
    session or run is using it.
    """
    operator = _get_owned_operator(session, current_user, operator_id)
    operator.restart_requested = True
    operator.restart_pending = True
    session.add(operator)
    session.commit()
    session.refresh(operator)
    return _out(operator)


class RelayTokenResp(BaseModel):
    """Where and how a browser connects to an Operator through the relay."""

    relay_url: str
    token: str


@router.post("/operators/{operator_id}/relay-token")
def post_operator_relay_token(
    session: SessionDep,
    signed_in: CurrentSession,
    operator_id: uuid.UUID,
    x_second_factor: Annotated[str | None, Header()] = None,
) -> RelayTokenResp:
    """Let the user's browser connect to one of their online Operators.

    This opens a shell on their machine, so it takes a signed-in session,
    not a token, that entered a second factor recently.
    """
    current_user = signed_in.user
    operator = _get_owned_operator(session, current_user, operator_id)
    users.require_second_factor(
        current_user, signed_in.session_id, x_second_factor
    )
    if not is_online(operator):
        raise HTTPException(409, "Operator is offline")
    return RelayTokenResp(
        relay_url=settings.relay_url,
        token=create_relay_token(
            "browser",
            operator_id=operator.id,
            user_id=current_user.id,
            expires_delta=timedelta(seconds=BROWSER_RELAY_TOKEN_SECONDS),
            grant=create_operator_grant(
                operator.id,
                current_user.id,
                timedelta(seconds=BROWSER_RELAY_TOKEN_SECONDS),
            ),
        ),
    )


class Workspace(WorkspaceInfo):
    """A workspace along with the Operator it's on."""

    operator_id: uuid.UUID
    operator_name: str
    operator_online: bool
    operator_asleep: bool
    # Sessions need a POSIX terminal, so they aren't offered on Windows
    operator_platform: str | None
    updated: str
    # Whether its project is on this hub, which ones only on the machine
    # aren't
    on_hub: bool


def _list_workspaces(
    session: SessionDep,
    user: User,
    owner_name: str | None = None,
    project_name: str | None = None,
) -> list[Workspace]:
    # Only the user's own Operators, so this reveals nothing about a
    # project beyond what the user's machines reported
    query = (
        select(OperatorWorkspace, Operator)
        .join(Operator)
        .where(Operator.user_id == user.id)
        .where(Operator.is_active)
        .order_by(col(Operator.name), col(OperatorWorkspace.path))
    )
    if owner_name is not None and project_name is not None:
        query = query.where(
            OperatorWorkspace.owner_name == owner_name.lower()
        ).where(OperatorWorkspace.project_name == project_name.lower())
    rows = session.exec(query).all()
    # Projects are matched by name, as reported, in one query
    names = {
        (ws.owner_name, ws.project_name)
        for ws, _ in rows
        if ws.owner_name and ws.project_name
    }
    on_hub: set[tuple[str, str]] = set()
    if names:
        found = session.exec(
            select(Account.name, Project.name)
            .join(Project, col(Project.owner_account_id) == Account.id)
            .where(col(Account.name).in_({o for o, _ in names}))
            .where(func.lower(Project.name).in_({n for _, n in names}))
        ).all()
        on_hub = {(o.lower(), n.lower()) for o, n in found}
    resp = []
    for ws, operator in rows:
        project = None
        if ws.owner_name and ws.project_name:
            project = f"{ws.owner_name}/{ws.project_name}"
        resp.append(
            Workspace(
                path=ws.path,
                kind="managed" if ws.kind == "managed" else "personal",
                project=project,
                branch=ws.branch,
                commit=ws.commit,
                dirty=ws.dirty,
                ahead=ws.ahead,
                behind=ws.behind,
                running=ws.running,
                running_stages=ws.run_state.get("running_stages") or [],
                running_since=ws.run_state.get("running_since"),
                last_run=ws.run_state.get("last_run"),
                in_use_by=ws.run_state.get("in_use_by"),
                last_activity=ws.run_state.get("last_activity"),
                agents=ws.run_state.get("agents") or [],
                updated=ws.updated.isoformat(),
                on_hub=(ws.owner_name, ws.project_name) in on_hub,
                operator_id=operator.id,
                operator_name=operator.name,
                operator_online=is_online(operator),
                operator_asleep=is_asleep(operator),
                operator_platform=operator.platform,
            )
        )
    return resp


@router.get("/workspaces")
def get_workspaces(
    session: SessionDep, current_user: CurrentUser
) -> list[Workspace]:
    """List the workspaces on all of the user's Operators."""
    return _list_workspaces(session, current_user)


@router.get("/projects/{owner_name}/{project_name}/workspaces")
def get_project_workspaces(
    owner_name: str,
    project_name: str,
    session: SessionDep,
    current_user: CurrentUser,
) -> list[Workspace]:
    """List a project's workspaces on the user's Operators."""
    return _list_workspaces(session, current_user, owner_name, project_name)
