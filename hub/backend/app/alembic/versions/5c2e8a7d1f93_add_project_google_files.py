"""Add project Google files

Revision ID: 5c2e8a7d1f93
Revises: ff043cba2b65
Create Date: 2026-11-10 12:00:00.000000

"""

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

# revision identifiers, used by Alembic.
revision = "5c2e8a7d1f93"
down_revision = "ff043cba2b65"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "projectgooglefile",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column(
            "file_id",
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=False,
        ),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("created", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("project_id", "file_id"),
    )


def downgrade():
    op.drop_table("projectgooglefile")
