"""Index project folders synced with Overleaf

Revision ID: a333fc5aa994
Revises: d4e5f6a7b8c9
Create Date: 2026-08-08 17:36:37.333010

Autogenerate also reported drift unrelated to this change: a dropped
``ck_account_name_lowercase`` check constraint, and foreign keys on
projectinvitation and userprojectaccess that it would have recreated
without their ``ondelete`` behaviour. Those are left alone here rather
than carried along by a migration about Overleaf links.
"""

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

# revision identifiers, used by Alembic.
revision = "a333fc5aa994"
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
    op.add_column(
        "project", sa.Column("overleaf_scanned", sa.DateTime(), nullable=True)
    )


def downgrade():
    op.drop_column("project", "overleaf_scanned")
    op.drop_index(
        op.f("ix_overleaflink_overleaf_project_id"), table_name="overleaflink"
    )
    op.drop_table("overleaflink")
