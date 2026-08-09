"""GitHub-less membership and invitations

Native (non-GitHub) project access plus shareable, optionally labeled and
emailed invite links, so users without GitHub accounts can be granted
collaborator access. Also makes ``account.github_name`` nullable for
email/Google signups (project owners still need one, enforced in the app layer).

Native access is folded into the existing ``userprojectaccess`` table rather
than a separate membership table: its ``access`` column is renamed to
``github_access`` (the permission GitHub reports, kept for drift detection) and
``role_id`` (the Calkit-native granted level) plus ``invited_by_user_id`` are
added alongside it.

Squashes the editor branch's migrations into one, chained after the releases
feature.

Revision ID: d4e5f6a7b8c9
Revises: f3a9c1b7e240
Create Date: 2026-07-08 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = "d4e5f6a7b8c9"
down_revision = "f3a9c1b7e240"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        "account", "github_name", existing_type=sa.VARCHAR(), nullable=True
    )
    # Fold native project access into the existing project-access table.
    op.alter_column(
        "userprojectaccess",
        "access",
        new_column_name="github_access",
        existing_type=sa.VARCHAR(length=32),
        existing_nullable=True,
    )
    op.add_column(
        "userprojectaccess",
        sa.Column("role_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "userprojectaccess",
        sa.Column("invited_by_user_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        op.f("userprojectaccess_invited_by_user_id_fkey"),
        "userprojectaccess",
        "user",
        ["invited_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_table(
        "projectinvitation",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column(
            "token_hash",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
        ),
        sa.Column("role_id", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created", sa.DateTime(), nullable=False),
        sa.Column("expires", sa.DateTime(), nullable=True),
        sa.Column("max_uses", sa.Integer(), nullable=True),
        sa.Column("use_count", sa.Integer(), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False),
        sa.Column(
            "name",
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=True,
        ),
        sa.Column(
            "email",
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["project.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["user.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_projectinvitation_token_hash"),
        "projectinvitation",
        ["token_hash"],
        unique=True,
    )


def downgrade():
    op.drop_index(
        op.f("ix_projectinvitation_token_hash"),
        table_name="projectinvitation",
    )
    op.drop_table("projectinvitation")
    op.drop_constraint(
        op.f("userprojectaccess_invited_by_user_id_fkey"),
        "userprojectaccess",
        type_="foreignkey",
    )
    op.drop_column("userprojectaccess", "invited_by_user_id")
    op.drop_column("userprojectaccess", "role_id")
    op.alter_column(
        "userprojectaccess",
        "github_access",
        new_column_name="access",
        existing_type=sa.VARCHAR(length=32),
        existing_nullable=True,
    )
    op.alter_column(
        "account", "github_name", existing_type=sa.VARCHAR(), nullable=False
    )
