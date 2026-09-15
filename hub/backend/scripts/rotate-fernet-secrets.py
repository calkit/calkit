"""Rotate encrypted secrets to the active Fernet key.

Usage:
    python scripts/rotate-fernet-secrets.py --dry-run
    python scripts/rotate-fernet-secrets.py

The active key is the first key in settings.fernet_keys. Decryption will use
all configured keys, which allows safe staged rotation.
"""

from __future__ import annotations

import argparse
import logging
from typing import Iterable

from app.db import make_session
from app.models import (
    UserExternalCredential,
    UserGitHubToken,
    UserOverleafToken,
    UserZenodoToken,
)
from app.security import decrypt_secret, encrypt_secret
from sqlalchemy.exc import ProgrammingError
from sqlmodel import Session, select

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Counter:
    def __init__(self) -> None:
        self.rows = 0
        self.fields = 0


# (model class, fields containing encrypted values)
TARGETS: list[tuple[type, tuple[str, ...]]] = [
    (UserGitHubToken, ("access_token", "refresh_token")),
    (UserZenodoToken, ("access_token", "refresh_token")),
    (UserOverleafToken, ("access_token",)),
    (UserExternalCredential, ("secret_payload",)),
]


def _iter_rows(session: Session, model: type) -> Iterable:
    return session.exec(select(model)).all()


def rotate_model_fields(
    session: Session,
    model: type,
    fields: tuple[str, ...],
    *,
    dry_run: bool,
    counter: Counter,
) -> None:
    try:
        rows = _iter_rows(session, model)
    except ProgrammingError:
        # Allows running on environments where new tables do not yet exist.
        logger.warning(
            "Skipping %s because table is not available", model.__name__
        )
        session.rollback()
        return

    model_rows = 0
    model_fields = 0
    for row in rows:
        model_rows += 1
        for field_name in fields:
            value = getattr(row, field_name, None)
            if not value:
                continue
            plaintext = decrypt_secret(value)
            new_ciphertext = encrypt_secret(plaintext)
            if not dry_run:
                setattr(row, field_name, new_ciphertext)
            model_fields += 1

    counter.rows += model_rows
    counter.fields += model_fields
    logger.info(
        "Processed %s rows in %s (%s encrypted fields)",
        model_rows,
        model.__name__,
        model_fields,
    )


def rotate_secrets(*, dry_run: bool) -> None:
    counter = Counter()
    with make_session() as session:
        for model, fields in TARGETS:
            rotate_model_fields(
                session=session,
                model=model,
                fields=fields,
                dry_run=dry_run,
                counter=counter,
            )
        if dry_run:
            session.rollback()
            logger.info("Dry run complete; no changes were written")
        else:
            session.commit()
            logger.info("Rotation complete; changes committed")

    logger.info(
        "Total rows processed: %s, total encrypted fields rewritten: %s",
        counter.rows,
        counter.fields,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Decrypt and re-encrypt in memory, but do not write changes",
    )
    args = parser.parse_args()
    rotate_secrets(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
