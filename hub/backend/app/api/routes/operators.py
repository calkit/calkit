"""Routes for Operators: Calkit processes on users' machines.

See docs/dev/operator-protocol.md for how these fit with the relay.
"""

import re
import secrets
import uuid
from datetime import timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Cookie, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import col, func, select

import app.projects
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
from app.messaging import generate_operator_email, send_email
from app.models import (
    Account,
    Message,
    Operator,
    OperatorPublic,
    OperatorWorkspace,
    Project,
    RefreshToken,
    User,
    UserToken,
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
# How long a request for a CLI token for an Operator's machine stands
CLI_TOKEN_REQUEST_SECONDS = 600
CLI_TOKEN_DAYS = 365
MAX_ACTIVE_OPERATORS = 50
NAME_PATTERN = r"^[a-z0-9][a-z0-9-]{0,63}$"
# Hub names for an owner and project, as an Operator reports them
PROJECT_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,255}/[A-Za-z0-9._-]{1,255}$")
MAX_INT = 2**31 - 1


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
    # Including when its owner was deactivated
    if not operator.is_active or not operator.user.is_active:
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
    """Add an Operator's current state to its record."""
    return OperatorOut.model_validate(
        operator,
        update=dict(
            is_online=is_online(operator),
            is_asleep=is_asleep(operator),
            workspace_count=len(operator.workspaces),
        ),
    )


class PublicKey(BaseModel):
    """A P-256 public key as a JSON Web Key, e.g., a browser's for one
    connection, or an Operator's own.

    The browser signs every message it sends the Operator with the private
    half of its key, which it can't export, so a grant naming this key is
    no use to the relay that carries it, and the Operator signs its replies
    with its own, so the relay can't forge those either.
    """

    kty: Literal["EC"]
    crv: Literal["P-256"]
    # Base64url coordinates of the point, 32 bytes each
    x: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")
    y: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")


def _check_public_key(key: PublicKey) -> None:
    """Refuse a key that isn't a point on P-256, which the other end would
    reject anyway, so the sender hears why now.
    """
    import base64

    from cryptography.hazmat.primitives.asymmetric import ec

    def coordinate(value: str) -> int:
        return int.from_bytes(base64.urlsafe_b64decode(value + "="), "big")

    try:
        ec.EllipticCurvePublicNumbers(
            coordinate(key.x), coordinate(key.y), ec.SECP256R1()
        ).public_key()
    except ValueError:
        raise HTTPException(422, "Invalid public key")


class OperatorPost(BaseModel):
    """What a machine reports about itself when registering."""

    name: str | None = Field(default=None, pattern=NAME_PATTERN)
    hostname: str | None = Field(default=None, max_length=255)
    machine_id: str | None = Field(default=None, max_length=255)
    platform: str | None = Field(default=None, max_length=64)
    calkit_version: str | None = Field(default=None, max_length=64)
    hosts: list[Annotated[str, Field(max_length=255)]] = Field(
        default=[], max_length=20
    )
    # Its own key, which it signs replies to browsers with; an Operator
    # installed over SSH sends it at its first check-in instead
    public_key: PublicKey | None = None


def _send_operator_email(
    operator: Operator, user: User, event: Literal["registered", "revoked"]
) -> None:
    """Tell the owner an Operator was registered or revoked, so one they
    didn't expect stands out.
    """
    if not settings.emails_enabled:
        return
    email_data = generate_operator_email(
        email_to=user.email,
        event=event,
        name=operator.name,
        hostname=operator.hostname,
        platform=operator.platform,
        machine_id=operator.machine_id,
    )
    send_email(
        email_to=user.email,
        subject=email_data.subject,
        html_content=email_data.html_content,
    )


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
    if req.public_key is not None:
        _check_public_key(req.public_key)
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
    if len(taken) >= MAX_ACTIVE_OPERATORS:
        raise HTTPException(409, "Too many Operators; revoke some first")
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
        public_key=req.public_key.model_dump() if req.public_key else None,
    )
    session.add(operator)
    session.commit()
    session.refresh(operator)
    _send_operator_email(operator, current_user, "registered")
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
    """Get one of the user's active Operators, or raise a 404 or 410."""
    operator = session.get(Operator, operator_id)
    if operator is None or operator.user_id != user.id:
        raise HTTPException(404, "Operator not found")
    if not operator.is_active:
        raise HTTPException(410, "Operator has been revoked")
    return operator


def _revoke(session: SessionDep, operator: Operator) -> OperatorOut:
    """Revoke an Operator, which stops at its next check-in, along with
    the CLI token issued to its machine.
    """
    # Kept rather than deleted so a revoked token can say it was revoked
    operator.is_active = False
    operator.cli_token_requested_at = None
    session.add(operator)
    tokens = session.exec(
        select(UserToken)
        .where(UserToken.operator_id == operator.id)
        .where(UserToken.is_active)
    ).all()
    for token in tokens:
        token.is_active = False
        session.add(token)
    session.commit()
    session.refresh(operator)
    _send_operator_email(operator, operator.user, "revoked")
    return _out(operator)


@router.delete("/operators/self")
def delete_operator_self(
    session: SessionDep, operator: CurrentOperator
) -> OperatorOut:
    """Revoke the Operator making the request, e.g., when it's uninstalled."""
    return _revoke(session, operator)


@router.delete("/operators/{operator_id}")
def delete_operator(
    session: SessionDep, signed_in: CurrentSession, operator_id: uuid.UUID
) -> OperatorOut:
    """Revoke an Operator, which takes a signed-in session, not a token."""
    operator = _get_owned_operator(session, signed_in.user, operator_id)
    return _revoke(session, operator)


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
    pid: int = Field(ge=0, le=MAX_INT)
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
    ahead: int | None = Field(default=None, ge=0, le=MAX_INT)
    behind: int | None = Field(default=None, ge=0, le=MAX_INT)
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
    # The sign-ins its open channels came from, to hear which have ended
    channel_sessions: list[uuid.UUID] = Field(default=[], max_length=100)
    # Its own key, which is stored if the hub has none yet, and otherwise
    # has to match
    public_key: PublicKey | None = None


class CheckInResp(BaseModel):
    """Where and how an Operator connects to the relay."""

    operator_id: uuid.UUID
    name: str
    user_id: uuid.UUID
    relay_url: str
    relay_token: str
    check_in_interval: int = CHECK_IN_INTERVAL_SECONDS
    # What grants are signed with, which the Operator takes from here
    grant_public_key: str
    # Whether an Operator in cron mode should connect
    connect: bool = False
    # Whether to restart once idle, as its owner asked
    restart: bool = False
    # Which of its channels' sign-ins have ended, e.g., with a password
    # change, so it closes those channels
    ended_sessions: list[uuid.UUID] = []


def _ended_sessions(
    session: SessionDep, operator: Operator, session_ids: list[uuid.UUID]
) -> list[uuid.UUID]:
    """Which of these sign-ins of the Operator's owner are no longer live."""
    if not session_ids:
        return []
    if not operator.user.is_active:
        return sorted(set(session_ids), key=str)
    live = session.exec(
        select(RefreshToken.session_id)
        .where(col(RefreshToken.session_id).in_(session_ids))
        .where(RefreshToken.user_id == operator.user_id)
        .where(RefreshToken.interactive)
        .where(RefreshToken.is_active)
        .where(RefreshToken.expires > utcnow())
    ).all()
    return sorted(set(session_ids) - set(live), key=str)


def _update_workspaces(
    session: SessionDep, operator: Operator, reported: list[WorkspaceInfo]
) -> None:
    """Make the Operator's stored workspaces match what it reported."""
    existing = {ws.path: ws for ws in operator.workspaces}
    now = utcnow()
    seen = set()
    for info in reported:
        # Only the first of any reported twice
        if info.path in seen:
            continue
        seen.add(info.path)
        ws = existing.pop(info.path, None)
        if ws is None:
            ws = OperatorWorkspace(operator_id=operator.id, path=info.path)
        owner = name = None
        if info.project and PROJECT_PATTERN.match(info.project):
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
    if req.public_key is not None:
        _check_public_key(req.public_key)
        key = req.public_key.model_dump()
        if operator.public_key is None:
            operator.public_key = key
        elif operator.public_key != key:
            raise HTTPException(409, "Operator key doesn't match")
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
        ended_sessions=_ended_sessions(
            session, operator, req.channel_sessions
        ),
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


class RelayTokenReq(BaseModel):
    """What a browser asking to connect to an Operator sends."""

    public_key: PublicKey


class RelayTokenResp(BaseModel):
    """Where and how a browser connects to an Operator through the relay,
    and how it checks the replies it gets are the Operator's.
    """

    relay_url: str
    token: str
    # The Operator's key, which signs its replies, and the ID of the grant
    # in the token, which they're bound to
    operator_public_key: PublicKey
    grant_id: str


SecondFactorCookie = Annotated[
    str | None, Cookie(alias=users.SECOND_FACTOR_COOKIE)
]


def _get_operator_for_session(
    session: SessionDep,
    signed_in: CurrentSession,
    operator_id: uuid.UUID,
    second_factor: str | None,
) -> tuple[Operator, int]:
    """Get one of the user's online Operators for a signed-in session that
    entered a second factor recently, and when that stops counting.
    """
    operator = _get_owned_operator(session, signed_in.user, operator_id)
    second_factor_expires = users.require_second_factor(
        signed_in.user, signed_in.session_id, second_factor
    )
    if not is_online(operator):
        raise HTTPException(409, "Operator is offline")
    return operator, second_factor_expires


@router.post("/operators/{operator_id}/relay-token")
def post_operator_relay_token(
    session: SessionDep,
    signed_in: CurrentSession,
    operator_id: uuid.UUID,
    req: RelayTokenReq,
    second_factor: SecondFactorCookie = None,
) -> RelayTokenResp:
    """Let the user's browser connect to one of their online Operators.

    This opens a shell on their machine, so it takes a signed-in session,
    not a token, that entered a second factor recently.
    """
    _check_public_key(req.public_key)
    operator, second_factor_expires = _get_operator_for_session(
        session, signed_in, operator_id, second_factor
    )
    if operator.public_key is None:
        raise HTTPException(409, "Operator hasn't sent its key yet")
    grant, grant_id = create_operator_grant(
        operator.id,
        signed_in.user.id,
        timedelta(seconds=BROWSER_RELAY_TOKEN_SECONDS),
        browser_key=req.public_key.model_dump(),
        session_id=signed_in.session_id,
        second_factor_expires=second_factor_expires,
    )
    return RelayTokenResp(
        relay_url=settings.relay_url,
        token=create_relay_token(
            "browser",
            operator_id=operator.id,
            user_id=signed_in.user.id,
            expires_delta=timedelta(seconds=BROWSER_RELAY_TOKEN_SECONDS),
            grant=grant,
        ),
        operator_public_key=PublicKey.model_validate(operator.public_key),
        grant_id=grant_id,
    )


@router.post("/operators/{operator_id}/cli-token-request")
def post_operator_cli_token_request(
    session: SessionDep,
    signed_in: CurrentSession,
    operator_id: uuid.UUID,
    second_factor: SecondFactorCookie = None,
) -> Message:
    """Let one of the user's Operators fetch a CLI token for its machine,
    within the next 10 minutes, so the token never crosses the relay.
    """
    operator, _ = _get_operator_for_session(
        session, signed_in, operator_id, second_factor
    )
    operator.cli_token_requested_at = utcnow()
    session.add(operator)
    session.commit()
    return Message(message="Token requested")


class CliToken(BaseModel):
    token: str


@router.post("/operators/cli-token")
def post_operator_cli_token(
    session: SessionDep, operator: CurrentOperator
) -> CliToken:
    """Issue the Operator's machine a CLI token, if its owner asked for one
    recently, replacing any it was issued before.
    """
    requested = operator.cli_token_requested_at
    if (
        requested is None
        or (utcnow() - requested).total_seconds() > CLI_TOKEN_REQUEST_SECONDS
    ):
        raise HTTPException(403, "No token was requested")
    operator.cli_token_requested_at = None
    session.add(operator)
    earlier = session.exec(
        select(UserToken)
        .where(UserToken.operator_id == operator.id)
        .where(UserToken.is_active)
    ).all()
    for token in earlier:
        token.is_active = False
        session.add(token)
    selector = secrets.token_hex(PAT_SELECTOR_LENGTH_BYTES)
    verifier = secrets.token_hex(PAT_VERIFIER_LENGTH_BYTES)
    session.add(
        UserToken(
            user_id=operator.user_id,
            expires=utcnow() + timedelta(days=CLI_TOKEN_DAYS),
            is_active=True,
            selector=selector,
            hashed_verifier=hash_token_verifier(verifier),
            description=f"Operator {operator.name}",
            operator_id=operator.id,
        )
    )
    session.commit()
    return CliToken(token=f"ckp_{selector}{verifier}")


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
    """The workspaces on the user's Operators, optionally for one project."""
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
        # Only ones the user can read, so this doesn't reveal that a private
        # project exists
        found = session.exec(
            select(Account.name, Project.name)
            .distinct()
            .join(Project, col(Project.owner_account_id) == Account.id)
            .join(Project.user_access_records, isouter=True)  # type: ignore[arg-type]
            .where(col(Account.name).in_({o for o, _ in names}))
            .where(func.lower(Project.name).in_({n for _, n in names}))
            .where(app.projects.readable_project_clause(user))
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
