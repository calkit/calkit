"""Delete a user, with their account and projects, so the next sign-in with
that identity starts from nothing.

Usage: python scripts/delete-user.py EMAIL [--force]
"""

import argparse
import logging
import sys

from app.config import settings
from app.db import engine
from app.models import User
from sqlmodel import Session, select

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("email")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow deleting outside a local environment",
    )
    args = parser.parse_args()
    if settings.ENVIRONMENT != "local" and not args.force:
        sys.exit(
            f"Refusing to delete a user in the {settings.ENVIRONMENT} "
            "environment without --force"
        )
    with Session(engine) as session:
        user = session.exec(
            select(User).where(User.email == args.email)
        ).first()
        if user is None:
            sys.exit(f"No user with email {args.email}")
        if user.is_superuser:
            # prestart recreates the first superuser, so deleting it only
            # gets it back without its GitHub link
            sys.exit(f"{args.email} is a superuser; use a regular account")
        account_name = user.account.name
        n_projects = len(user.account.owned_projects)
        session.delete(user)
        session.commit()
    logger.info(
        f"Deleted {args.email} ({account_name}) and {n_projects} project(s)"
    )


if __name__ == "__main__":
    main()
