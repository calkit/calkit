"""Add user emails and which connection reaches storage

Revision ID: 49bf0f23df64
Revises: 56dfc88b0e4c
Create Date: 2026-11-24 18:16:44.274789

"""

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

# revision identifiers, used by Alembic.
revision = "49bf0f23df64"
down_revision = "56dfc88b0e4c"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "useremail",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "email",
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=False,
        ),
        sa.Column(
            "source",
            sqlmodel.sql.sqltypes.AutoString(length=64),
            nullable=False,
        ),
        sa.Column("credential_id", sa.Uuid(), nullable=True),
        sa.Column("verified_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["credential_id"],
            ["userexternalcredential.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index(
        op.f("ix_useremail_credential_id"),
        "useremail",
        ["credential_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_useremail_user_id"), "useremail", ["user_id"], unique=False
    )
    op.add_column(
        "storageresource", sa.Column("credential_id", sa.Uuid(), nullable=True)
    )
    op.create_index(
        op.f("ix_storageresource_credential_id"),
        "storageresource",
        ["credential_id"],
        unique=False,
    )
    op.create_foreign_key(
        "storageresource_credential_id_fkey",
        "storageresource",
        "userexternalcredential",
        ["credential_id"],
        ["id"],
        ondelete="CASCADE",
    )
    # Each user had one connection per service, which is what reached their
    # storage
    op.execute(
        """
        UPDATE storageresource AS r
        SET credential_id = c.id
        FROM userexternalcredential AS c
        WHERE c.user_id = r.credential_user_id
            AND c.label = 'default'
            AND c.provider = CASE r.kind
                WHEN 'hf-bucket' THEN 'huggingface'
                WHEN 'box-folder' THEN 'box'
            END
        """
    )
    # Box logins already connected count as their users' emails, except
    # where another user has them
    op.execute(
        """
        INSERT INTO useremail (
            id, user_id, email, source, credential_id, verified_at
        )
        SELECT
            gen_random_uuid(),
            c.user_id,
            lower(c.metadata_json->>'login'),
            'box',
            c.id,
            now()
        FROM userexternalcredential AS c
        JOIN "user" AS u ON u.id = c.user_id
        WHERE c.provider = 'box'
            AND c.metadata_json->>'login' IS NOT NULL
            AND lower(c.metadata_json->>'login') <> lower(u.email)
            AND NOT EXISTS (
                SELECT 1 FROM "user" AS o
                WHERE lower(o.email) = lower(c.metadata_json->>'login')
            )
        ON CONFLICT (email) DO NOTHING
        """
    )


def downgrade():
    op.drop_constraint(
        "storageresource_credential_id_fkey",
        "storageresource",
        type_="foreignkey",
    )
    op.drop_index(
        op.f("ix_storageresource_credential_id"),
        table_name="storageresource",
    )
    op.drop_column("storageresource", "credential_id")
    op.drop_index(op.f("ix_useremail_user_id"), table_name="useremail")
    op.drop_index(op.f("ix_useremail_credential_id"), table_name="useremail")
    op.drop_table("useremail")
