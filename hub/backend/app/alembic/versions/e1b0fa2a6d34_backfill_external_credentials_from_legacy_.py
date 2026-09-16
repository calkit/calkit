"""Backfill external credentials from legacy token tables.

Revision ID: e1b0fa2a6d34
Revises: c7c41c3f0d22
Create Date: 2026-03-06 13:05:00.000000

"""

from __future__ import annotations

import json
import uuid

from alembic import context, op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e1b0fa2a6d34"
down_revision = "c7c41c3f0d22"
branch_labels = None
depends_on = None


legacy_github = sa.table(
    "usergithubtoken",
    sa.column("user_id", sa.Uuid()),
    sa.column("updated", sa.DateTime()),
    sa.column("access_token", sa.String()),
    sa.column("refresh_token", sa.String()),
    sa.column("expires", sa.DateTime()),
    sa.column("refresh_token_expires", sa.DateTime()),
)

legacy_zenodo = sa.table(
    "userzenodotoken",
    sa.column("user_id", sa.Uuid()),
    sa.column("updated", sa.DateTime()),
    sa.column("access_token", sa.String()),
    sa.column("refresh_token", sa.String()),
    sa.column("expires", sa.DateTime()),
    sa.column("refresh_token_expires", sa.DateTime()),
)

legacy_overleaf = sa.table(
    "useroverleaftoken",
    sa.column("user_id", sa.Uuid()),
    sa.column("updated", sa.DateTime()),
    sa.column("access_token", sa.String()),
    sa.column("expires", sa.DateTime()),
)

external = sa.table(
    "userexternalcredential",
    sa.column("id", sa.Uuid()),
    sa.column("user_id", sa.Uuid()),
    sa.column("provider", sa.String()),
    sa.column("credential_type", sa.String()),
    sa.column("label", sa.String()),
    sa.column("secret_payload", sa.String()),
    sa.column("scopes", sa.String()),
    sa.column("provider_account_id", sa.String()),
    sa.column("metadata_json", sa.JSON()),
    sa.column("updated", sa.DateTime()),
    sa.column("expires", sa.DateTime()),
    sa.column("refresh_token_expires", sa.DateTime()),
)


def _exists(bind: sa.Connection, user_id: uuid.UUID, provider: str) -> bool:
    statement = sa.select(sa.literal(True)).where(
        external.c.user_id == user_id,
        external.c.provider == provider,
        external.c.label == "default",
    )
    return bind.execute(statement).first() is not None


def _insert_oauth2(
    *,
    bind: sa.Connection,
    user_id: uuid.UUID,
    provider: str,
    access_token: str,
    refresh_token: str,
    updated,
    expires,
    refresh_token_expires,
) -> None:
    from app.security import decrypt_secret, encrypt_secret

    payload = json.dumps(
        {
            "access_token": decrypt_secret(access_token),
            "refresh_token": decrypt_secret(refresh_token),
        }
    )
    bind.execute(
        external.insert().values(
            id=uuid.uuid4(),
            user_id=user_id,
            provider=provider,
            credential_type="oauth2",
            label="default",
            secret_payload=encrypt_secret(payload),
            scopes=None,
            provider_account_id=None,
            metadata_json={"migrated_from": f"user{provider}token"},
            updated=updated,
            expires=expires,
            refresh_token_expires=refresh_token_expires,
        )
    )


def _insert_pat(
    *,
    bind: sa.Connection,
    user_id: uuid.UUID,
    provider: str,
    access_token: str,
    updated,
    expires,
) -> None:
    from app.security import decrypt_secret, encrypt_secret

    payload = json.dumps({"access_token": decrypt_secret(access_token)})
    bind.execute(
        external.insert().values(
            id=uuid.uuid4(),
            user_id=user_id,
            provider=provider,
            credential_type="pat",
            label="default",
            secret_payload=encrypt_secret(payload),
            scopes=None,
            provider_account_id=None,
            metadata_json={"migrated_from": f"user{provider}token"},
            updated=updated,
            expires=expires,
            refresh_token_expires=None,
        )
    )


def upgrade():
    # This migration transforms ciphertext shape and requires runtime decrypt/
    # encrypt operations, so skip in alembic --sql mode.
    if context.is_offline_mode():
        return

    bind = op.get_bind()

    for row in bind.execute(sa.select(legacy_github)).mappings():
        if _exists(bind, row["user_id"], "github"):
            continue
        _insert_oauth2(
            bind=bind,
            user_id=row["user_id"],
            provider="github",
            access_token=row["access_token"],
            refresh_token=row["refresh_token"],
            updated=row["updated"],
            expires=row["expires"],
            refresh_token_expires=row["refresh_token_expires"],
        )

    for row in bind.execute(sa.select(legacy_zenodo)).mappings():
        if _exists(bind, row["user_id"], "zenodo"):
            continue
        _insert_oauth2(
            bind=bind,
            user_id=row["user_id"],
            provider="zenodo",
            access_token=row["access_token"],
            refresh_token=row["refresh_token"],
            updated=row["updated"],
            expires=row["expires"],
            refresh_token_expires=row["refresh_token_expires"],
        )

    for row in bind.execute(sa.select(legacy_overleaf)).mappings():
        if _exists(bind, row["user_id"], "overleaf"):
            continue
        _insert_pat(
            bind=bind,
            user_id=row["user_id"],
            provider="overleaf",
            access_token=row["access_token"],
            updated=row["updated"],
            expires=row["expires"],
        )


def downgrade():
    # Keep downgrade non-destructive for migrated external credentials.
    pass
