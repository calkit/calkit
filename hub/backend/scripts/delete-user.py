"""Delete a user, with their account and everything that refers to either,
so the next sign-in with that identity starts from nothing.

Usage: python scripts/delete-user.py EMAIL [--force]
"""

import argparse
import logging
import sys
from collections import Counter

from app.config import settings
from app.db import engine
from app.models import User
from sqlalchemy import Table, delete, select, update
from sqlmodel import Session, SQLModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def wipe(
    session: Session,
    table: Table,
    ids: list,
    seen: set,
    counts: Counter,
) -> None:
    """Delete rows by primary key, taking dependents with them.

    Rows that must point at a doomed row are deleted first, recursively;
    rows that merely may (a nullable foreign key, e.g., who created an org)
    are unlinked instead.
    """
    for other in SQLModel.metadata.tables.values():
        for fk in other.foreign_keys:
            if fk.column.table is not table:
                continue
            col = fk.parent
            if col.nullable and not col.primary_key:
                session.execute(
                    update(other).where(col.in_(ids)).values({col.name: None})
                )
                continue
            pk = list(other.primary_key.columns)
            if len(pk) == 1:
                child_ids = [
                    row[0]
                    for row in session.execute(
                        select(pk[0]).where(col.in_(ids))
                    )
                    if (other.name, row[0]) not in seen
                ]
                seen.update((other.name, i) for i in child_ids)
                if child_ids:
                    wipe(session, other, child_ids, seen, counts)
            res = session.execute(delete(other).where(col.in_(ids)))
            counts[other.name] += res.rowcount
    pk = list(table.primary_key.columns)[0]
    res = session.execute(delete(table).where(pk.in_(ids)))
    counts[table.name] += res.rowcount


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
        user = session.execute(
            select(User).where(User.email == args.email)
        ).scalar_one_or_none()
        if user is None:
            sys.exit(f"No user with email {args.email}")
        if user.is_superuser:
            # prestart recreates the first superuser, so deleting it only
            # gets it back without its GitHub link
            sys.exit(f"{args.email} is a superuser; use a regular account")
        account_name = user.account.name
        counts: Counter = Counter()
        seen: set = set()
        # The account owns the projects, so it goes first with everything
        # under it; the user's own tokens, votes, and flags follow
        wipe(session, user.account.__table__, [user.account.id], seen, counts)
        wipe(session, User.__table__, [user.id], seen, counts)
        session.commit()
    deleted = ", ".join(f"{n} {t}" for t, n in sorted(counts.items()) if n)
    logger.info(f"Deleted {args.email} ({account_name}): {deleted}")


if __name__ == "__main__":
    main()
