"""Add user external credential table

Revision ID: c7c41c3f0d22
Revises: ed74edb0a9e6
Create Date: 2026-03-06 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = "c7c41c3f0d22"
down_revision = "ed74edb0a9e6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "userexternalcredential",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column(
            "credential_type",
            sqlmodel.sql.sqltypes.AutoString(length=64),
            nullable=False,
        ),
        sa.Column("label", sqlmodel.sql.sqltypes.AutoString(length=128), nullable=False),
        sa.Column("secret_payload", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("scopes", sqlmodel.sql.sqltypes.AutoString(length=2048), nullable=True),
        sa.Column(
            "provider_account_id",
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=True,
        ),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("updated", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires", sa.DateTime(), nullable=True),
        sa.Column("refresh_token_expires", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "provider",
            "label",
            name="uq_userexternalcredential_user_provider_label",
        ),
    )
    op.create_index(
        "ix_userexternalcredential_user_provider",
        "userexternalcredential",
        ["user_id", "provider"],
        unique=False,
    )


def downgrade():
    op.drop_index(
        "ix_userexternalcredential_user_provider",
        table_name="userexternalcredential",
    )
    op.drop_table("userexternalcredential")
