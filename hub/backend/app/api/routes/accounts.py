"""API endpoints for accounts."""

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException
from sqlmodel import SQLModel, select

from app.api.deps import CurrentUserOptional, SessionDep
from app.models import Account

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()


class AccountPublic(SQLModel):
    name: str
    github_name: str | None
    display_name: str
    kind: Literal["user", "org"]
    role: Literal["self", "read", "write", "admin", "owner"] | None = None


@router.get("/accounts/{account_name}")
def get_account(
    account_name: str,
    session: SessionDep,
    current_user: CurrentUserOptional,
) -> AccountPublic:
    account_query = select(Account).where(Account.name == account_name.lower())
    account = session.exec(account_query).first()
    if account is None:
        raise HTTPException(
            404, f"Account '{account_name}' not found or inaccessible."
        )
    account_dict = dict(account)
    account_dict["kind"] = (
        "org" if account_dict.get("org_id") is not None else "user"
    )
    # Determine role and display name
    role = None
    if current_user is not None:
        if current_user.id == account.user_id:
            role = "self"
        else:
            # Check org access
            for org_membership in current_user.org_memberships:
                if org_membership.org_id == account.org_id:
                    role = org_membership.role_name
                    break
    account_dict["role"] = role
    account_dict["display_name"] = account.display_name or account.name
    return AccountPublic.model_validate(account_dict)
