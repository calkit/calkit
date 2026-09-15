"""Consolidate comments into unified projectcomment

Revision ID: c1f9a3e27d48
Revises: e1b0fa2a6d34
Create Date: 2026-04-01 00:00:00.000000

Migrates all existing figurecomment rows into the new unified projectcomment
table (artifact_type='figure'), and introduces the notification table used by
comment fan-out. Also adds git_ref and git_rev to track the git context at
the time each comment was posted.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c1f9a3e27d48'
down_revision = 'e1b0fa2a6d34'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'notification',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('project_id', sa.Uuid(), nullable=False),
        sa.Column('message', sa.String(length=500), nullable=False),
        sa.Column('link', sa.String(length=2048), nullable=False),
        sa.Column('read', sa.DateTime(), nullable=True),
        sa.Column('created', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['project.id']),
        sa.ForeignKeyConstraint(['user_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.add_column('figurecomment', sa.Column('resolved', sa.DateTime(), nullable=True))

    # Add parent_id to figurecomment so it can be migrated with thread info
    op.add_column(
        'figurecomment',
        sa.Column('parent_id', sa.Uuid(), sa.ForeignKey('figurecomment.id'), nullable=True),
    )

    op.create_table(
        'projectcomment',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('project_id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('created', sa.DateTime(), nullable=False),
        sa.Column('updated', sa.DateTime(), nullable=False),
        sa.Column('comment', sa.Text(), nullable=False),
        sa.Column('artifact_path', sa.String(length=512), nullable=True),
        sa.Column('artifact_type', sa.String(length=50), nullable=True),
        sa.Column('highlight', sa.JSON(), nullable=True),
        sa.Column('parent_id', sa.Uuid(), nullable=True),
        sa.Column('external_url', sa.String(length=2048), nullable=True),
        sa.Column('resolved', sa.DateTime(), nullable=True),
        sa.Column('git_ref', sa.String(length=256), nullable=True),
        sa.Column('git_rev', sa.String(length=40), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['project.id']),
        sa.ForeignKeyConstraint(['user_id'], ['user.id']),
        sa.ForeignKeyConstraint(['parent_id'], ['projectcomment.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    # Migrate figure comments (no highlight column in figurecomment)
    op.execute("""
        INSERT INTO projectcomment
            (id, project_id, user_id, created, updated, comment,
             artifact_path, artifact_type, highlight, parent_id,
             external_url, resolved)
        SELECT
            id, project_id, user_id, created, updated, comment,
            figure_path, 'figure', NULL, parent_id,
            external_url, resolved
        FROM figurecomment
    """)

    op.drop_table('figurecomment')

    # Allow notifications to reference a specific comment
    op.add_column(
        'notification',
        sa.Column('project_comment_id', sa.Uuid(), sa.ForeignKey('projectcomment.id'), nullable=True),
    )


def downgrade():
    # Recreate figurecomment as it existed before this migration chain.
    op.create_table(
        'figurecomment',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('project_id', sa.Uuid(), nullable=False),
        sa.Column('figure_path', sa.String(length=255), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('created', sa.DateTime(), nullable=False),
        sa.Column('updated', sa.DateTime(), nullable=False),
        sa.Column('external_url', sa.String(length=2048), nullable=True),
        sa.Column('comment', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['project.id']),
        sa.ForeignKeyConstraint(['user_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    # Restore figure comments (drop thread info since figurecomment has no parent_id).
    op.execute("""
        INSERT INTO figurecomment
            (id, project_id, user_id, created, updated, comment,
             figure_path, external_url)
        SELECT
            id, project_id, user_id, created, updated, comment,
            artifact_path, external_url
        FROM projectcomment WHERE artifact_type = 'figure'
    """)

    op.drop_column('notification', 'project_comment_id')
    op.drop_table('projectcomment')
    op.drop_table('notification')
