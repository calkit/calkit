"""Add table indexing project folders synced with Overleaf

Revision ID: b8c1d4e97f30
Revises: d4e5f6a7b8c9
Create Date: 2026-08-08 09:00:00.000000

"""

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

# revision identifiers, used by Alembic.
revision = "b8c1d4e97f30"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "overleaflink",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("path", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column(
            "overleaf_project_id",
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=False,
        ),
        sa.Column("updated", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
        sa.PrimaryKeyConstraint("project_id", "path"),
    )
    op.create_index(
        op.f("ix_overleaflink_overleaf_project_id"),
        "overleaflink",
        ["overleaf_project_id"],
        unique=False,
    )


def downgrade():
    op.drop_index(
        op.f("ix_overleaflink_overleaf_project_id"),
        table_name="overleaflink",
    )
    op.drop_table("overleaflink")
