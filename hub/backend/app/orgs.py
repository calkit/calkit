"""Functionality for working with orgs."""

from app.models import Org
from sqlmodel import Session, select


def get_org_from_db(org_name: str, session: Session) -> Org | None:
    query = select(Org).where(Org.account.has(name=org_name))  # type: ignore
    return session.exec(query).first()


def get_org_by_github_name(session: Session, github_name: str) -> Org | None:
    return get_org_from_db(org_name=github_name.lower(), session=session)
