"""Add releases feature (releases, share tokens, comments, viewers, votes)

Squashes the releases branch's migrations into one:
afa35dae8954, aabd30a6b15b, 69f55a987c11, 026f9b3efef9, a80ecaf727ed.

Revision ID: f3a9c1b7e240
Revises: dcef842dee10
Create Date: 2026-06-26 16:30:00.000000

"""

from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = "f3a9c1b7e240"
down_revision = "dcef842dee10"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "release",
        sa.Column(
            "name",
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=False,
        ),
        sa.Column(
            "kind", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False
        ),
        sa.Column(
            "path", sqlmodel.sql.sqltypes.AutoString(length=512), nullable=True
        ),
        sa.Column(
            "description",
            sqlmodel.sql.sqltypes.AutoString(length=2048),
            nullable=True,
        ),
        sa.Column(
            "git_ref",
            sqlmodel.sql.sqltypes.AutoString(length=256),
            nullable=True,
        ),
        sa.Column(
            "git_rev",
            sqlmodel.sql.sqltypes.AutoString(length=40),
            nullable=True,
        ),
        sa.Column("public", sa.Boolean(), nullable=False),
        sa.Column(
            "url", sqlmodel.sql.sqltypes.AutoString(length=2048), nullable=True
        ),
        sa.Column(
            "doi", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("view_count", sa.Integer(), nullable=False),
        sa.Column(
            "github_release_url",
            sqlmodel.sql.sqltypes.AutoString(length=2048),
            nullable=True,
        ),
        sa.Column("created", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["user.id"],
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id", "name", name="uq_release_project_name"
        ),
    )
    op.create_table(
        "releasesharetoken",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("release_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "token_hash",
            sqlmodel.sql.sqltypes.AutoString(length=64),
            nullable=False,
        ),
        sa.Column(
            "email",
            sqlmodel.sql.sqltypes.AutoString(length=320),
            nullable=True,
        ),
        sa.Column(
            "permission",
            sqlmodel.sql.sqltypes.AutoString(length=16),
            nullable=False,
        ),
        sa.Column(
            "note", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True
        ),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("revoked", sa.Boolean(), nullable=False),
        sa.Column("view_count", sa.Integer(), nullable=False),
        sa.Column("created", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["user.id"],
        ),
        sa.ForeignKeyConstraint(
            ["release_id"],
            ["release.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_releasesharetoken_token_hash"),
        "releasesharetoken",
        ["token_hash"],
        unique=True,
    )
    op.create_table(
        "releasecomment",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("release_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("share_token_id", sa.Uuid(), nullable=True),
        sa.Column(
            "author_name",
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=True,
        ),
        sa.Column(
            "author_email",
            sqlmodel.sql.sqltypes.AutoString(length=320),
            nullable=True,
        ),
        sa.Column(
            "git_rev",
            sqlmodel.sql.sqltypes.AutoString(length=40),
            nullable=True,
        ),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("highlight", sa.JSON(), nullable=True),
        sa.Column(
            "external_url",
            sqlmodel.sql.sqltypes.AutoString(length=2048),
            nullable=True,
        ),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("resolved", sa.DateTime(), nullable=True),
        sa.Column("created", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["releasecomment.id"],
            name="fk_releasecomment_parent_id",
        ),
        sa.ForeignKeyConstraint(
            ["release_id"],
            ["release.id"],
        ),
        sa.ForeignKeyConstraint(
            ["share_token_id"], ["releasesharetoken.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "featurevote",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "feature",
            sqlmodel.sql.sqltypes.AutoString(length=64),
            nullable=False,
        ),
        sa.Column("created", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "feature", name="featurevote_user_id_feature_key"
        ),
    )
    op.create_index(
        op.f("ix_featurevote_feature"),
        "featurevote",
        ["feature"],
        unique=False,
    )
    op.create_table(
        "releaseviewer",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("release_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("share_token_id", sa.Uuid(), nullable=True),
        sa.Column("created", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["release_id"], ["release.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["share_token_id"], ["releasesharetoken.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "release_id",
            "share_token_id",
            name="uq_releaseviewer_release_token",
        ),
        sa.UniqueConstraint(
            "release_id", "user_id", name="uq_releaseviewer_release_user"
        ),
    )


def downgrade():
    op.drop_table("releaseviewer")
    op.drop_index(op.f("ix_featurevote_feature"), table_name="featurevote")
    op.drop_table("featurevote")
    op.drop_table("releasecomment")
    op.drop_index(
        op.f("ix_releasesharetoken_token_hash"), table_name="releasesharetoken"
    )
    op.drop_table("releasesharetoken")
    op.drop_table("release")
