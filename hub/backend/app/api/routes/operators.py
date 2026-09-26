"""Routes for Operators: Calkit processes on users' machines.

See docs/dev/operator-protocol.md for how these fit with the relay.
"""

import re
import secrets
import uuid
from datetime import timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import select

from app.api.deps import (
    PAT_SELECTOR_END_CHAR_IDX,
    PAT_SELECTOR_LENGTH_BYTES,
    PAT_VERIFIER_LENGTH_BYTES,
    CurrentUser,
    SessionDep,
    TokenDep,
)
from app.config import settings
from app.core import utcnow
from app.models import Operator, OperatorPublic, User
from app.security import (
    create_relay_token,
    get_password_hash,
    verify_password,
)

router = APIRouter()

TOKEN_PREFIX = "cko_"
CHECK_IN_INTERVAL_SECONDS = 60
# Missing this many check-ins in a row means the Operator is offline
OFFLINE_AFTER_MISSED_CHECK_INS = 3
OPERATOR_RELAY_TOKEN_MINUTES = 10
BROWSER_RELAY_TOKEN_SECONDS = 60


def get_current_operator(session: SessionDep, token: TokenDep) -> Operator:
    if not token.startswith(TOKEN_PREFIX):
        raise HTTPException(403, "Not an Operator token")
    selector = token[len(TOKEN_PREFIX) : PAT_SELECTOR_END_CHAR_IDX]
    verifier = token[PAT_SELECTOR_END_CHAR_IDX:]
    operator = session.exec(
        select(Operator).where(Operator.selector == selector)
    ).first()
    if operator is None or not verify_password(
        verifier, operator.hashed_verifier
    ):
        raise HTTPException(403, "Invalid token")
    if not operator.is_active:
        raise HTTPException(403, "Operator has been revoked")
    return operator


CurrentOperator = Annotated[Operator, Depends(get_current_operator)]


def is_online(operator: Operator) -> bool:
    if operator.last_seen is None:
        return False
    age = (utcnow() - operator.last_seen).total_seconds()
    return age < CHECK_IN_INTERVAL_SECONDS * OFFLINE_AFTER_MISSED_CHECK_INS


def require_second_factor(user: User) -> None:
    """Refuse to open sessions for users without a second factor.

    The hub has no two-factor authentication yet, so this passes; once it
    does, this is the one place that enforces it for Operators.
    """
    return


class OperatorOut(OperatorPublic):
    is_online: bool


def _out(operator: Operator) -> OperatorOut:
    return OperatorOut.model_validate(
        operator, update=dict(is_online=is_online(operator))
    )


class OperatorPost(BaseModel):
    name: str | None = Field(default=None, max_length=64)
    hostname: str | None = Field(default=None, max_length=255)
    machine_id: str | None = Field(default=None, max_length=255)
    platform: str | None = Field(default=None, max_length=64)
    calkit_version: str | None = Field(default=None, max_length=64)
    hosts: list[str] = []


class OperatorRegistered(OperatorOut):
    token: str


@router.post("/operators")
def post_operator(
    session: SessionDep, current_user: CurrentUser, req: OperatorPost
) -> OperatorRegistered:
    # Names default to the hostname, suffixed until unique for the user
    base = req.name or re.sub(
        r"[^a-z0-9-]+", "-", (req.hostname or "operator").lower()
    ).strip("-")
    base = base[:56] or "operator"
    taken = set(
        session.exec(
            select(Operator.name).where(Operator.user_id == current_user.id)
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
        hashed_verifier=get_password_hash(verifier),
    )
    session.add(operator)
    session.commit()
    session.refresh(operator)
    return OperatorRegistered.model_validate(
        _out(operator),
        update=dict(token=f"{TOKEN_PREFIX}{selector}{verifier}"),
    )


@router.get("/operators")
def get_operators(
    session: SessionDep, current_user: CurrentUser
) -> list[OperatorOut]:
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
    operator = _get_owned_operator(session, current_user, operator_id)
    # Kept rather than deleted so a revoked token can say it was revoked
    operator.is_active = False
    session.add(operator)
    session.commit()
    session.refresh(operator)
    return _out(operator)


class WorkspaceInfo(BaseModel):
    path: str = Field(max_length=4096)
    kind: Literal["personal", "managed"] = "personal"
    # The project as "owner/name", if known
    project: str | None = Field(default=None, max_length=256)
    branch: str | None = Field(default=None, max_length=256)
    commit: str | None = Field(default=None, max_length=64)
    dirty: bool | None = None
    ahead: int | None = None
    behind: int | None = None


class CheckIn(BaseModel):
    calkit_version: str | None = Field(default=None, max_length=64)
    workspaces: list[WorkspaceInfo] = Field(default=[], max_length=1000)


class CheckInResp(BaseModel):
    operator_id: uuid.UUID
    name: str
    user_id: uuid.UUID
    relay_url: str
    relay_token: str
    check_in_interval: int = CHECK_IN_INTERVAL_SECONDS


@router.post("/operators/check-in")
def post_operator_check_in(
    session: SessionDep, operator: CurrentOperator, req: CheckIn
) -> CheckInResp:
    operator.last_seen = utcnow()
    operator.workspaces = [w.model_dump() for w in req.workspaces]
    if req.calkit_version is not None:
        operator.calkit_version = req.calkit_version
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
    )


class RelayTokenResp(BaseModel):
    relay_url: str
    token: str


@router.post("/operators/{operator_id}/relay-token")
def post_operator_relay_token(
    session: SessionDep, current_user: CurrentUser, operator_id: uuid.UUID
) -> RelayTokenResp:
    operator = _get_owned_operator(session, current_user, operator_id)
    require_second_factor(current_user)
    if not is_online(operator):
        raise HTTPException(409, "Operator is offline")
    return RelayTokenResp(
        relay_url=settings.relay_url,
        token=create_relay_token(
            "browser",
            operator_id=operator.id,
            user_id=current_user.id,
            expires_delta=timedelta(seconds=BROWSER_RELAY_TOKEN_SECONDS),
        ),
    )


class ProjectWorkspace(WorkspaceInfo):
    operator_id: uuid.UUID
    operator_name: str
    operator_online: bool


@router.get("/projects/{owner_name}/{project_name}/workspaces")
def get_project_workspaces(
    owner_name: str,
    project_name: str,
    session: SessionDep,
    current_user: CurrentUser,
) -> list[ProjectWorkspace]:
    # Only the user's own Operators, so this reveals nothing about the
    # project beyond what the user's machines reported
    project = f"{owner_name}/{project_name}".lower()
    operators = session.exec(
        select(Operator)
        .where(Operator.user_id == current_user.id)
        .where(Operator.is_active)
    ).all()
    resp = []
    for operator in operators:
        online = is_online(operator)
        for ws in operator.workspaces:
            ws_project: Any = ws.get("project")
            if not isinstance(ws_project, str):
                continue
            if ws_project.lower() != project:
                continue
            resp.append(
                ProjectWorkspace(
                    **ws,
                    operator_id=operator.id,
                    operator_name=operator.name,
                    operator_online=online,
                )
            )
    return resp
