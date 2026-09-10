"""Add contribution requests and tasks

Revision ID: 2b3ce70d7ecc
Revises: 97762605447f
Create Date: 2026-09-09 15:22:52.857210

"""

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

# revision identifiers, used by Alembic.
revision = "2b3ce70d7ecc"
down_revision = "97762605447f"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "contribrequest",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "token_hash",
            sqlmodel.sql.sqltypes.AutoString(length=64),
            nullable=False,
        ),
        sa.Column(
            "title",
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=False,
        ),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column(
            "direction",
            sqlmodel.sql.sqltypes.AutoString(length=16),
            nullable=False,
        ),
        sa.Column("in_response_to_request_id", sa.Uuid(), nullable=True),
        sa.Column(
            "target_kind",
            sqlmodel.sql.sqltypes.AutoString(length=32),
            nullable=False,
        ),
        sa.Column(
            "target_path",
            sqlmodel.sql.sqltypes.AutoString(length=512),
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
        sa.Column(
            "permission",
            sqlmodel.sql.sqltypes.AutoString(length=16),
            nullable=False,
        ),
        sa.Column(
            "identity_requirement",
            sqlmodel.sql.sqltypes.AutoString(length=16),
            nullable=False,
        ),
        sa.Column("due_at", sa.DateTime(), nullable=True),
        sa.Column("round", sa.Integer(), nullable=False),
        sa.Column("supersedes_request_id", sa.Uuid(), nullable=True),
        sa.Column(
            "email",
            sqlmodel.sql.sqltypes.AutoString(length=320),
            nullable=True,
        ),
        sa.Column(
            "contributor_name",
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=True,
        ),
        sa.Column("public", sa.Boolean(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("max_responses", sa.Integer(), nullable=True),
        sa.Column(
            "approval_status",
            sqlmodel.sql.sqltypes.AutoString(length=16),
            nullable=False,
        ),
        sa.Column("approved_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column(
            "denial_reason",
            sqlmodel.sql.sqltypes.AutoString(length=1024),
            nullable=True,
        ),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("revoked", sa.Boolean(), nullable=False),
        sa.Column(
            "reply_key",
            sqlmodel.sql.sqltypes.AutoString(length=64),
            nullable=True,
        ),
        sa.Column(
            "github_issue_url",
            sqlmodel.sql.sqltypes.AutoString(length=2048),
            nullable=True,
        ),
        sa.Column("view_count", sa.Integer(), nullable=False),
        sa.Column("created", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["approved_by_user_id"],
            ["user.id"],
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["user.id"],
        ),
        sa.ForeignKeyConstraint(
            ["in_response_to_request_id"],
            ["contribrequest.id"],
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_request_id"],
            ["contribrequest.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_contribrequest_project_id"),
        "contribrequest",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_contribrequest_reply_key"),
        "contribrequest",
        ["reply_key"],
        unique=True,
    )
    op.create_index(
        op.f("ix_contribrequest_token_hash"),
        "contribrequest",
        ["token_hash"],
        unique=True,
    )
    op.create_table(
        "contribrequestresponse",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "responder_name",
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=True,
        ),
        sa.Column(
            "responder_email",
            sqlmodel.sql.sqltypes.AutoString(length=320),
            nullable=True,
        ),
        sa.Column("email_verified", sa.Boolean(), nullable=False),
        sa.Column(
            "status",
            sqlmodel.sql.sqltypes.AutoString(length=16),
            nullable=False,
        ),
        sa.Column(
            "via", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False
        ),
        sa.Column(
            "external_message_id",
            sqlmodel.sql.sqltypes.AutoString(length=512),
            nullable=True,
        ),
        sa.Column(
            "external_thread_url",
            sqlmodel.sql.sqltypes.AutoString(length=2048),
            nullable=True,
        ),
        sa.Column(
            "decline_reason",
            sqlmodel.sql.sqltypes.AutoString(length=1024),
            nullable=True,
        ),
        sa.Column(
            "recommendation",
            sqlmodel.sql.sqltypes.AutoString(length=32),
            nullable=True,
        ),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("confidential_note", sa.Text(), nullable=True),
        sa.Column(
            "git_rev",
            sqlmodel.sql.sqltypes.AutoString(length=40),
            nullable=True,
        ),
        sa.Column(
            "branch_name",
            sqlmodel.sql.sqltypes.AutoString(length=256),
            nullable=True,
        ),
        sa.Column(
            "github_pr_url",
            sqlmodel.sql.sqltypes.AutoString(length=2048),
            nullable=True,
        ),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("reviewed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("created", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["request_id"], ["contribrequest.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_user_id"],
            ["user.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_contribrequestresponse_request_id"),
        "contribrequestresponse",
        ["request_id"],
        unique=False,
    )
    op.create_table(
        "contribattachment",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=True),
        sa.Column("response_id", sa.Uuid(), nullable=True),
        sa.Column(
            "filename",
            sqlmodel.sql.sqltypes.AutoString(length=512),
            nullable=False,
        ),
        sa.Column(
            "content_type",
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=True,
        ),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column(
            "storage_key",
            sqlmodel.sql.sqltypes.AutoString(length=1024),
            nullable=False,
        ),
        sa.Column("uploaded_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["request_id"], ["contribrequest.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["response_id"], ["contribrequestresponse.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_user_id"],
            ["user.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "task",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("response_id", sa.Uuid(), nullable=True),
        sa.Column(
            "title",
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=False,
        ),
        sa.Column(
            "kind", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False
        ),
        sa.Column(
            "path", sqlmodel.sql.sqltypes.AutoString(length=512), nullable=True
        ),
        sa.Column("original_text", sa.Text(), nullable=True),
        sa.Column("suggested_text", sa.Text(), nullable=True),
        sa.Column("highlight", sa.JSON(), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column(
            "source",
            sqlmodel.sql.sqltypes.AutoString(length=16),
            nullable=False,
        ),
        sa.Column("attachment_id", sa.Uuid(), nullable=True),
        sa.Column(
            "source_ref",
            sqlmodel.sql.sqltypes.AutoString(length=64),
            nullable=True,
        ),
        sa.Column(
            "stage",
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=True,
        ),
        sa.Column(
            "anchor_status",
            sqlmodel.sql.sqltypes.AutoString(length=16),
            nullable=False,
        ),
        sa.Column("anchor_line", sa.Integer(), nullable=True),
        sa.Column("context_before", sa.Text(), nullable=True),
        sa.Column("context_after", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sqlmodel.sql.sqltypes.AutoString(length=16),
            nullable=False,
        ),
        sa.Column(
            "verdict",
            sqlmodel.sql.sqltypes.AutoString(length=16),
            nullable=True,
        ),
        sa.Column("assigned_to_user_id", sa.Uuid(), nullable=True),
        sa.Column("board_position", sa.Float(), nullable=False),
        sa.Column("due", sa.DateTime(), nullable=True),
        sa.Column(
            "github_issue_url",
            sqlmodel.sql.sqltypes.AutoString(length=2048),
            nullable=True,
        ),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("decided_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column(
            "applied_git_rev",
            sqlmodel.sql.sqltypes.AutoString(length=40),
            nullable=True,
        ),
        sa.Column("created", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["assigned_to_user_id"],
            ["user.id"],
        ),
        sa.ForeignKeyConstraint(
            ["attachment_id"],
            ["contribattachment.id"],
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["user.id"],
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_user_id"],
            ["user.id"],
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
        ),
        sa.ForeignKeyConstraint(
            ["response_id"], ["contribrequestresponse.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_task_project_id"), "task", ["project_id"], unique=False
    )
    op.create_index(
        op.f("ix_task_response_id"), "task", ["response_id"], unique=False
    )
    op.create_index(op.f("ix_task_status"), "task", ["status"], unique=False)
    op.add_column(
        "project",
        sa.Column(
            "comment_access",
            sqlmodel.sql.sqltypes.AutoString(length=32),
            nullable=False,
            server_default="viewers",
        ),
    )


def downgrade():
    op.drop_column("project", "comment_access")
    op.drop_index(op.f("ix_task_status"), table_name="task")
    op.drop_index(op.f("ix_task_response_id"), table_name="task")
    op.drop_index(op.f("ix_task_project_id"), table_name="task")
    op.drop_table("task")
    op.drop_table("contribattachment")
    op.drop_index(
        op.f("ix_contribrequestresponse_request_id"),
        table_name="contribrequestresponse",
    )
    op.drop_table("contribrequestresponse")
    op.drop_index(
        op.f("ix_contribrequest_token_hash"), table_name="contribrequest"
    )
    op.drop_index(
        op.f("ix_contribrequest_reply_key"), table_name="contribrequest"
    )
    op.drop_index(
        op.f("ix_contribrequest_project_id"), table_name="contribrequest"
    )
    op.drop_table("contribrequest")
