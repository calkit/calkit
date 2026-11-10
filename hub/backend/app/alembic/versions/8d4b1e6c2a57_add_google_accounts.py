"""Add Google accounts

Revision ID: 8d4b1e6c2a57
Revises: 5c2e8a7d1f93
Create Date: 2026-11-10 18:00:00.000000

"""

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

# revision identifiers, used by Alembic.
revision = "8d4b1e6c2a57"
down_revision = "5c2e8a7d1f93"
branch_labels = None
depends_on = None


def upgrade():
    # A Google credential whose account is known is labeled with its email
    op.execute(
        "UPDATE userexternalcredential "
        "SET label = lower(provider_account_id) "
        "WHERE provider = 'google' AND provider_account_id IS NOT NULL"
    )
    op.create_index(
        "uq_userexternalcredential_google_account",
        "userexternalcredential",
        ["provider", "label"],
        unique=True,
        postgresql_where=sa.text("provider = 'google' AND label != 'default'"),
    )
    op.add_column(
        "projectgooglefile",
        sa.Column(
            "google_account",
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=True,
        ),
    )


def downgrade():
    op.drop_column("projectgooglefile", "google_account")
    # Labels are left, since someone may have more than one Google account,
    # which the code before this sees as not connected
    op.drop_index(
        "uq_userexternalcredential_google_account",
        table_name="userexternalcredential",
    )
