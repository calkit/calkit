"""Add project pipeline runs

Revision ID: 06716a686a81
Revises: e6b898df78ed

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = '06716a686a81'
down_revision = 'e6b898df78ed'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'projectpipelinerun',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('project_id', sa.Uuid(), nullable=False),
        sa.Column(
            'location', sqlmodel.sql.sqltypes.AutoString(), nullable=False
        ),
        sa.Column(
            'status', sqlmodel.sql.sqltypes.AutoString(), nullable=False
        ),
        sa.Column('created', sa.DateTime(), nullable=False),
        sa.Column('started', sa.DateTime(), nullable=True),
        sa.Column('finished', sa.DateTime(), nullable=True),
        sa.Column(
            'git_rev', sqlmodel.sql.sqltypes.AutoString(), nullable=True
        ),
        sa.Column('branch', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('started_by_user_id', sa.Uuid(), nullable=True),
        sa.Column(
            'started_by', sqlmodel.sql.sqltypes.AutoString(), nullable=True
        ),
        sa.Column('url', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column(
            'github_workflow',
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=True,
        ),
        sa.Column('github_run_id', sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['project.id']),
        sa.ForeignKeyConstraint(
            ['started_by_user_id'], ['user.id'], ondelete='SET NULL'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id', 'github_run_id'),
    )
    op.create_index(
        op.f('ix_projectpipelinerun_project_id'),
        'projectpipelinerun',
        ['project_id'],
        unique=False,
    )


def downgrade():
    op.drop_index(
        op.f('ix_projectpipelinerun_project_id'),
        table_name='projectpipelinerun',
    )
    op.drop_table('projectpipelinerun')
