"""Routes for machines: users' computers linked to the hub.

See docs/dev/hub-link-protocol.md for how these fit with the relay.
"""

import re
import secrets
import time
import uuid
from datetime import UTC, datetime, timedelta
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
from app.messaging import generate_machine_email, send_email
from app.models import (
    Account,
    Machine,
    MachinePublic,
    MachineWorkspace,
    Message,
    Project,
    RefreshToken,
    User,
    UserToken,
)
from app.security import (
    create_access_token,
    create_machine_grant,
    create_relay_token,
    decode_machine_grant,
    get_machine_grant_public_key,
    hash_token_verifier,
    verify_token_verifier,
)

router = APIRouter()

TOKEN_PREFIX = "ckm_"
CHECK_IN_INTERVAL_SECONDS = 60
# Missing this many check-ins in a row means the machine is offline
OFFLINE_AFTER_MISSED_CHECK_INS = 3
# Machines in cron mode check in this often, connecting only when asked
CRON_CHECK_IN_INTERVAL_SECONDS = 300
# How long a request to connect stands before it lapses
CONNECT_REQUEST_SECONDS = 900
MACHINE_RELAY_TOKEN_MINUTES = 10
BROWSER_RELAY_TOKEN_SECONDS = 60
# How long a request for a CLI token for a machine stands
CLI_TOKEN_REQUEST_SECONDS = 600
CLI_TOKEN_DAYS = 365
# How long a token for Calkit in a machine's session lasts, which the
# machine asks for again as it runs out, so it stops soon after what let
# the session open does
SESSION_TOKEN_MINUTES = 15
MAX_ACTIVE_MACHINES = 50
NAME_PATTERN = r"^[a-z0-9][a-z0-9-]{0,63}$"
# Hub names for an owner and project, as a machine reports them
PROJECT_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,255}/[A-Za-z0-9._-]{1,255}$")
MAX_INT = 2**31 - 1


def get_current_machine(session: SessionDep, token: TokenDep) -> Machine:
    """Authenticate a request made with a machine token."""
    if not token.startswith(TOKEN_PREFIX):
        raise HTTPException(403, "Not a machine token")
    selector = token[len(TOKEN_PREFIX) : PAT_SELECTOR_END_CHAR_IDX]
    verifier = token[PAT_SELECTOR_END_CHAR_IDX:]
    machine = session.exec(
        select(Machine).where(Machine.selector == selector)
    ).first()
    if machine is None or not verify_token_verifier(
        verifier, machine.hashed_verifier
    ):
        raise HTTPException(403, "Invalid token")
    # Including when its owner was deactivated
    if not machine.is_active or not machine.user.is_active:
        raise HTTPException(403, "Machine has been revoked")
    return machine


CurrentMachine = Annotated[Machine, Depends(get_current_machine)]


def is_online(machine: Machine) -> bool:
    """Whether it's connected to the relay, as of a recent check-in."""
    if machine.last_seen is None or not machine.connected:
        return False
    age = (utcnow() - machine.last_seen).total_seconds()
    return age < CHECK_IN_INTERVAL_SECONDS * OFFLINE_AFTER_MISSED_CHECK_INS


def is_asleep(machine: Machine) -> bool:
    """Whether it's in cron mode and still checking in, just not connected."""
    if machine.mode != "cron" or machine.last_seen is None:
        return False
    if is_online(machine):
        return False
    age = (utcnow() - machine.last_seen).total_seconds()
    return (
        age < CRON_CHECK_IN_INTERVAL_SECONDS * OFFLINE_AFTER_MISSED_CHECK_INS
    )


def connect_requested(machine: Machine) -> bool:
    """Whether its owner asked it to connect recently enough to still do so."""
    if machine.connect_requested_at is None:
        return False
    age = (utcnow() - machine.connect_requested_at).total_seconds()
    return age < CONNECT_REQUEST_SECONDS


class MachineOut(MachinePublic):
    """A machine as the API returns it: its record plus its current state."""

    is_online: bool
    is_asleep: bool
    workspace_count: int


def _out(machine: Machine, workspace_count: int | None = None) -> MachineOut:
    """Add a machine's current state to its record."""
    if workspace_count is None:
        workspace_count = len(machine.workspaces)
    return MachineOut.model_validate(
        machine,
        update=dict(
            is_online=is_online(machine),
            is_asleep=is_asleep(machine),
            workspace_count=workspace_count,
        ),
    )


class PublicKey(BaseModel):
    """A P-256 public key as a JSON Web Key, e.g., a browser's for one
    connection, or a machine's own.

    The browser signs every message it sends the machine with the private
    half of its key, which it can't export, so a grant naming this key is
    no use to the relay that carries it, and the machine signs its replies
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


class MachinePost(BaseModel):
    """What a machine reports about itself when registering."""

    name: str | None = Field(default=None, pattern=NAME_PATTERN)
    hostname: str | None = Field(default=None, max_length=255)
    machine_id: str | None = Field(default=None, max_length=255)
    platform: str | None = Field(default=None, max_length=64)
    calkit_version: str | None = Field(default=None, max_length=64)
    hosts: list[Annotated[str, Field(max_length=255)]] = Field(
        default=[], max_length=20
    )
    # Its own key, which it signs replies to browsers with; a machine
    # installed over SSH sends it at its first check-in instead
    public_key: PublicKey | None = None


def _send_machine_email(
    machine: Machine, user: User, event: Literal["linked", "unlinked"]
) -> None:
    """Tell the owner a machine was registered or revoked, so one they
    didn't expect stands out.
    """
    if not settings.emails_enabled:
        return
    email_data = generate_machine_email(
        email_to=user.email,
        event=event,
        name=machine.name,
        hostname=machine.hostname,
        platform=machine.platform,
        machine_id=machine.system_machine_id,
    )
    send_email(
        email_to=user.email,
        subject=email_data.subject,
        html_content=email_data.html_content,
    )


class MachineRegistered(MachineOut):
    """A newly registered machine, with the token only returned here."""

    token: str
    # Pinned by the machine to check the grants browsers connect with
    grant_public_key: str


@router.post("/machines")
def post_machine(
    session: SessionDep, current_user: CurrentUser, req: MachinePost
) -> MachineRegistered:
    """Register a machine as one of the user's."""
    # Setting up the second factor that opening sessions takes proves
    # itself by email, so that address has to be the user's
    if not current_user.email_verified:
        raise HTTPException(403, "Verify your email first")
    if req.public_key is not None:
        _check_public_key(req.public_key)
    # Names default to the hostname, cut to leave room for a suffix added
    # until unique for the user
    base = req.name or (
        re.sub(r"[^a-z0-9-]+", "-", (req.hostname or "machine").lower())
        .strip("-")[:56]
        .strip("-")
        or "machine"
    )
    taken = set(
        session.exec(
            select(Machine.name)
            .where(Machine.user_id == current_user.id)
            .where(Machine.is_active)
        ).all()
    )
    if len(taken) >= MAX_ACTIVE_MACHINES:
        raise HTTPException(409, "Too many machines; revoke some first")
    if req.name is not None and req.name in taken:
        raise HTTPException(409, f"A machine named '{req.name}' exists")
    name = base
    n = 2
    while name in taken:
        name = f"{base}-{n}"
        n += 1
    selector = secrets.token_hex(PAT_SELECTOR_LENGTH_BYTES)
    verifier = secrets.token_hex(PAT_VERIFIER_LENGTH_BYTES)
    machine = Machine(
        user_id=current_user.id,
        name=name,
        hostname=req.hostname,
        system_machine_id=req.machine_id,
        platform=req.platform,
        calkit_version=req.calkit_version,
        hosts=req.hosts or ([req.hostname] if req.hostname else []),
        selector=selector,
        hashed_verifier=hash_token_verifier(verifier),
        public_key=req.public_key.model_dump() if req.public_key else None,
    )
    session.add(machine)
    session.commit()
    session.refresh(machine)
    _send_machine_email(machine, current_user, "linked")
    return MachineRegistered.model_validate(
        _out(machine),
        update=dict(
            token=f"{TOKEN_PREFIX}{selector}{verifier}",
            grant_public_key=get_machine_grant_public_key(),
        ),
    )


@router.get("/machines")
def get_machines(
    session: SessionDep, current_user: CurrentUser
) -> list[MachineOut]:
    """List the user's machines that haven't been revoked."""
    machines = session.exec(
        select(Machine)
        .where(Machine.user_id == current_user.id)
        .where(Machine.is_active)
        .order_by(Machine.name)  # type: ignore[arg-type]
    ).all()
    # Counted in one query rather than loading each machine's
    counts = dict(
        session.exec(
            select(MachineWorkspace.machine_id, func.count())
            .where(
                col(MachineWorkspace.machine_id).in_([o.id for o in machines])
            )
            .group_by(col(MachineWorkspace.machine_id))
        ).all()
    )
    return [_out(o, counts.get(o.id, 0)) for o in machines]


def _get_owned_machine(
    session: SessionDep, user: User, machine_id: uuid.UUID
) -> Machine:
    """Get one of the user's active machines, or raise a 404 or 410."""
    machine = session.get(Machine, machine_id)
    if machine is None or machine.user_id != user.id:
        raise HTTPException(404, "Machine not found")
    if not machine.is_active:
        raise HTTPException(410, "Machine has been revoked")
    return machine


def _revoke(session: SessionDep, machine: Machine) -> MachineOut:
    """Revoke a machine, which stops at its next check-in, along with
    the CLI token issued to its machine.
    """
    # Kept rather than deleted so a revoked token can say it was revoked
    machine.is_active = False
    machine.cli_token_requested_at = None
    session.add(machine)
    tokens = session.exec(
        select(UserToken)
        .where(UserToken.machine_id == machine.id)
        .where(UserToken.is_active)
    ).all()
    for token in tokens:
        token.is_active = False
        session.add(token)
    session.commit()
    session.refresh(machine)
    _send_machine_email(machine, machine.user, "unlinked")
    return _out(machine)


@router.get("/machines/self")
def get_machine_self(machine: CurrentMachine) -> MachineOut:
    """Get the machine making the request, e.g., to check it's still
    registered without its owner's login.
    """
    return _out(machine)


@router.delete("/machines/self")
def delete_machine_self(
    session: SessionDep, machine: CurrentMachine
) -> MachineOut:
    """Revoke the machine making the request, e.g., when it's unlinked."""
    return _revoke(session, machine)


@router.delete("/machines/{machine_id}")
def delete_machine(
    session: SessionDep, signed_in: CurrentSession, machine_id: uuid.UUID
) -> MachineOut:
    """Revoke a machine, which takes a signed-in session, not a token."""
    machine = _get_owned_machine(session, signed_in.user, machine_id)
    return _revoke(session, machine)


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
    # In one of the machine's sessions, a tmux pane, which can be attached
    # to, or another terminal, e.g., an editor's
    where: Literal["session", "tmux", "terminal"] = "terminal"
    # What it was started from, e.g., 'Code'
    app: str | None = Field(default=None, max_length=256)
    # What it was named, and what it's doing, if it says
    name: str | None = Field(default=None, max_length=256)
    status: str | None = Field(default=None, max_length=64)


class WorkspaceInfo(BaseModel):
    """A workspace as a machine reports it at check-in."""

    path: str = Field(max_length=4096)
    kind: Literal["personal", "managed"] = "personal"
    # The project as "owner/name", if known, up to 128 characters each
    project: str | None = Field(default=None, max_length=257)
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
    # Another hub this machine is linked to that's using it, which
    # keeps this one out until it's done
    in_use_by: str | None = Field(default=None, max_length=2048)
    # When it last changed, e.g., a commit, a checkout, or a run ending
    last_activity: str | None = Field(default=None, max_length=64)
    agents: list[AgentInfo] = Field(default=[], max_length=20)


class CheckIn(BaseModel):
    """What a machine reports each time it checks in."""

    calkit_version: str | None = Field(default=None, max_length=64)
    mode: Literal["service", "foreground", "cron"] | None = None
    # False when a machine in cron mode is only asking whether to connect
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
    """Where and how a machine connects to the relay."""

    machine_id: uuid.UUID
    name: str
    user_id: uuid.UUID
    relay_url: str
    relay_token: str
    check_in_interval: int = CHECK_IN_INTERVAL_SECONDS
    # What grants are signed with, which the machine takes from here
    grant_public_key: str
    # Whether a machine in cron mode should connect
    connect: bool = False
    # Whether to restart once idle, as its owner asked
    restart: bool = False
    # Which of its channels' sign-ins have ended, e.g., with a password
    # change, so it closes those channels
    ended_sessions: list[uuid.UUID] = []


def _ended_sessions(
    session: SessionDep, machine: Machine, session_ids: list[uuid.UUID]
) -> list[uuid.UUID]:
    """Which of these sign-ins of the machine's owner are no longer live."""
    if not session_ids:
        return []
    if not machine.user.is_active:
        return sorted(set(session_ids), key=str)
    live = session.exec(
        select(RefreshToken.session_id)
        .where(col(RefreshToken.session_id).in_(session_ids))
        .where(RefreshToken.user_id == machine.user_id)
        .where(RefreshToken.interactive)
        .where(RefreshToken.is_active)
        .where(RefreshToken.expires > utcnow())
    ).all()
    return sorted(set(session_ids) - set(live), key=str)


@router.post("/machines/check-in")
def post_machine_check_in(
    session: SessionDep, machine: CurrentMachine, req: CheckIn
) -> CheckInResp:
    """Record that a machine is alive and what it has, and tell it how
    to connect.
    """

    def update_workspaces(
        session: SessionDep, machine: Machine, reported: list[WorkspaceInfo]
    ) -> None:
        """Make the machine's stored workspaces match what it reported."""
        existing = {ws.path: ws for ws in machine.workspaces}
        now = utcnow()
        seen = set()
        for info in reported:
            # Only the first of any reported twice
            if info.path in seen:
                continue
            seen.add(info.path)
            ws = existing.pop(info.path, None)
            is_new = ws is None
            if ws is None:
                ws = MachineWorkspace(machine_id=machine.id, path=info.path)
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
            # Most check-ins change nothing, which then writes nothing
            if is_new or session.is_modified(ws):
                ws.updated = now
                session.add(ws)
        for ws in existing.values():
            session.delete(ws)

    if req.public_key is not None:
        _check_public_key(req.public_key)
        key = req.public_key.model_dump()
        if machine.public_key is None:
            machine.public_key = key
        elif machine.public_key != key:
            raise HTTPException(409, "Machine key doesn't match")
    machine.last_seen = utcnow()
    update_workspaces(session, machine, req.workspaces)
    if req.calkit_version is not None:
        machine.calkit_version = req.calkit_version
    if req.mode is not None:
        machine.mode = req.mode
    machine.connected = req.connected
    # A request to connect is answered once it has
    if req.connected:
        machine.connect_requested_at = None
    # As is a request to restart, which stays pending until it has
    restart = machine.restart_requested
    machine.restart_requested = False
    machine.restart_pending = req.restart_pending or restart
    session.add(machine)
    session.commit()
    session.refresh(machine)
    return CheckInResp(
        machine_id=machine.id,
        name=machine.name,
        user_id=machine.user_id,
        relay_url=settings.relay_url,
        relay_token=create_relay_token(
            "machine",
            machine_id=machine.id,
            user_id=machine.user_id,
            expires_delta=timedelta(minutes=MACHINE_RELAY_TOKEN_MINUTES),
        ),
        connect=connect_requested(machine),
        restart=restart,
        grant_public_key=get_machine_grant_public_key(),
        ended_sessions=_ended_sessions(session, machine, req.channel_sessions),
    )


@router.post("/machines/{machine_id}/wake")
def post_machine_wake(
    session: SessionDep, current_user: CurrentUser, machine_id: uuid.UUID
) -> MachineOut:
    """Ask a machine in cron mode to connect at its next check-in."""
    machine = _get_owned_machine(session, current_user, machine_id)
    machine.connect_requested_at = utcnow()
    session.add(machine)
    session.commit()
    session.refresh(machine)
    return _out(machine)


@router.post("/machines/{machine_id}/restart")
def post_machine_restart(
    session: SessionDep, current_user: CurrentUser, machine_id: uuid.UUID
) -> MachineOut:
    """Ask a machine to restart, e.g., to run a newer Calkit, once no
    session or run is using it.
    """
    machine = _get_owned_machine(session, current_user, machine_id)
    machine.restart_requested = True
    machine.restart_pending = True
    session.add(machine)
    session.commit()
    session.refresh(machine)
    return _out(machine)


class RelayTokenReq(BaseModel):
    """What a browser asking to connect to a machine sends."""

    public_key: PublicKey


class RelayTokenResp(BaseModel):
    """Where and how a browser connects to a machine through the relay,
    and how it checks the replies it gets are the machine's.
    """

    relay_url: str
    token: str
    # The machine's key, which signs its replies, and the ID of the grant
    # in the token, which they're bound to
    machine_public_key: PublicKey
    grant_id: str


SecondFactorCookie = Annotated[
    str | None, Cookie(alias=users.SECOND_FACTOR_COOKIE)
]


def _get_machine_for_session(
    session: SessionDep,
    signed_in: CurrentSession,
    machine_id: uuid.UUID,
    second_factor: str | None,
) -> tuple[Machine, int]:
    """Get one of the user's online machines for a signed-in session that
    entered a second factor recently, and when that stops counting.
    """
    machine = _get_owned_machine(session, signed_in.user, machine_id)
    second_factor_expires = users.require_second_factor(
        signed_in.user, signed_in.session_id, second_factor
    )
    if not is_online(machine):
        raise HTTPException(409, "Machine is offline")
    return machine, second_factor_expires


@router.post("/machines/{machine_id}/relay-token")
def post_machine_relay_token(
    session: SessionDep,
    signed_in: CurrentSession,
    machine_id: uuid.UUID,
    req: RelayTokenReq,
    second_factor: SecondFactorCookie = None,
) -> RelayTokenResp:
    """Let the user's browser connect to one of their online machines.

    This opens a shell on their machine, so it takes a signed-in session,
    not a token, that entered a second factor recently.
    """
    _check_public_key(req.public_key)
    machine, second_factor_expires = _get_machine_for_session(
        session, signed_in, machine_id, second_factor
    )
    if machine.public_key is None:
        raise HTTPException(409, "Machine hasn't sent its key yet")
    grant, grant_id = create_machine_grant(
        machine.id,
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
            machine_id=machine.id,
            user_id=signed_in.user.id,
            expires_delta=timedelta(seconds=BROWSER_RELAY_TOKEN_SECONDS),
            grant=grant,
        ),
        machine_public_key=PublicKey.model_validate(machine.public_key),
        grant_id=grant_id,
    )


@router.post("/machines/{machine_id}/cli-token-request")
def post_machine_cli_token_request(
    session: SessionDep,
    signed_in: CurrentSession,
    machine_id: uuid.UUID,
    second_factor: SecondFactorCookie = None,
) -> Message:
    """Let one of the user's machines fetch a CLI token for itself,
    within the next 10 minutes, so the token never crosses the relay.
    """
    machine, _ = _get_machine_for_session(
        session, signed_in, machine_id, second_factor
    )
    machine.cli_token_requested_at = utcnow()
    session.add(machine)
    session.commit()
    return Message(message="Token requested")


class CliToken(BaseModel):
    token: str


@router.post("/machines/cli-token")
def post_machine_cli_token(
    session: SessionDep, machine: CurrentMachine
) -> CliToken:
    """Issue the machine a CLI token, if its owner asked for one
    recently, replacing any it was issued before.
    """
    requested = machine.cli_token_requested_at
    if (
        requested is None
        or (utcnow() - requested).total_seconds() > CLI_TOKEN_REQUEST_SECONDS
    ):
        raise HTTPException(403, "No token was requested")
    machine.cli_token_requested_at = None
    session.add(machine)
    earlier = session.exec(
        select(UserToken)
        .where(UserToken.machine_id == machine.id)
        .where(UserToken.is_active)
    ).all()
    for token in earlier:
        token.is_active = False
        session.add(token)
    selector = secrets.token_hex(PAT_SELECTOR_LENGTH_BYTES)
    verifier = secrets.token_hex(PAT_VERIFIER_LENGTH_BYTES)
    session.add(
        UserToken(
            user_id=machine.user_id,
            expires=utcnow() + timedelta(days=CLI_TOKEN_DAYS),
            is_active=True,
            selector=selector,
            hashed_verifier=hash_token_verifier(verifier),
            description=f"Machine {machine.name}",
            machine_id=machine.id,
        )
    )
    session.commit()
    return CliToken(token=f"ckp_{selector}{verifier}")


class SessionCredentialsReq(BaseModel):
    """What a machine shows to get credentials for one of its sessions: the
    grant of the channel that opened it, or last attached to it.
    """

    grant: str = Field(max_length=8192)


def _check_session_grant(
    session: SessionDep, machine: Machine, grant: str
) -> tuple[uuid.UUID, int]:
    """The sign-in whose grant opened a session on the machine, and when
    the second factor it entered expires, if both still count.

    Only the API can sign grants, and only the machine has its token, so
    neither the relay, which carries grants, nor anyone with the machine's
    token alone can get credentials.
    """
    refused = HTTPException(
        403,
        "The sign-in that opened this session has ended or needs its second "
        "factor again; open the session from the hub again",
    )
    payload = decode_machine_grant(grant, machine.id)
    if payload is None or payload["sub"] != str(machine.user_id):
        raise refused
    try:
        sign_in = uuid.UUID(str(payload["sid"]))
    except ValueError:
        raise refused
    tfa_exp, issued = payload["tfa_exp"], payload["iat"]
    if (
        not isinstance(tfa_exp, int)
        or isinstance(tfa_exp, bool)
        or tfa_exp <= time.time()
        or not isinstance(issued, int)
    ):
        raise refused
    # A second factor set up again since, or turned off, doesn't vouch for
    # what the old one let open
    totp = machine.user.totp
    if (
        totp is None
        or totp.confirmed_at is None
        or datetime.fromtimestamp(issued, tz=UTC).replace(tzinfo=None)
        < totp.confirmed_at.replace(microsecond=0)
    ):
        raise refused
    if _ended_sessions(session, machine, [sign_in]):
        raise refused
    return sign_in, tfa_exp


@router.post("/machines/session-token")
def post_machine_session_token(
    session: SessionDep, machine: CurrentMachine, req: SessionCredentialsReq
) -> CliToken:
    """Issue a short-lived token for Calkit in one of the machine's sessions,
    for as long as the sign-in that opened it and its second factor last.

    It stops working once the machine is unlinked or that sign-in ends, and
    can't make other tokens.
    """
    sign_in, tfa_exp = _check_session_grant(session, machine, req.grant)
    lifetime = min(SESSION_TOKEN_MINUTES * 60, tfa_exp - time.time())
    token = create_access_token(
        machine.user_id,
        timedelta(seconds=lifetime),
        add_payload={"machine_id": str(machine.id), "link_sid": str(sign_in)},
    )
    return CliToken(token=token)


@router.post("/machines/github-token")
def post_machine_github_token(
    session: SessionDep, machine: CurrentMachine, req: SessionCredentialsReq
) -> CliToken:
    """Get the owner's GitHub token for Git in one of the machine's sessions,
    on the same terms as a session token.
    """
    _check_session_grant(session, machine, req.grant)
    return CliToken(token=users.get_github_token(session, machine.user))


class Workspace(WorkspaceInfo):
    """A workspace along with the machine it's on."""

    machine_id: uuid.UUID
    machine_name: str
    machine_online: bool
    machine_asleep: bool
    # Sessions need a POSIX terminal, so they aren't offered on Windows
    machine_platform: str | None
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
    """The workspaces on the user's machines, optionally for one project."""
    # Only the user's own machines, so this reveals nothing about a
    # project beyond what the user's machines reported
    query = (
        select(MachineWorkspace, Machine)
        .join(Machine)
        .where(Machine.user_id == user.id)
        .where(Machine.is_active)
        .order_by(col(Machine.name), col(MachineWorkspace.path))
    )
    if owner_name is not None and project_name is not None:
        query = query.where(
            MachineWorkspace.owner_name == owner_name.lower()
        ).where(MachineWorkspace.project_name == project_name.lower())
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
    for ws, machine in rows:
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
                machine_id=machine.id,
                machine_name=machine.name,
                machine_online=is_online(machine),
                machine_asleep=is_asleep(machine),
                machine_platform=machine.platform,
            )
        )
    return resp


@router.get("/workspaces")
def get_workspaces(
    session: SessionDep, current_user: CurrentUser
) -> list[Workspace]:
    """List the workspaces on all of the user's machines."""
    return _list_workspaces(session, current_user)


@router.get("/projects/{owner_name}/{project_name}/workspaces")
def get_project_workspaces(
    owner_name: str,
    project_name: str,
    session: SessionDep,
    current_user: CurrentUser,
) -> list[Workspace]:
    """List a project's workspaces on the user's machines."""
    return _list_workspaces(session, current_user, owner_name, project_name)
