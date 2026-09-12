"""Add onboarding flags, feedback, email verification, and DVC pushes

Revision ID: 97762605447f
Revises: a333fc5aa994

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = '97762605447f'
down_revision = 'a333fc5aa994'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('useronboardingflag',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=True),
    sa.Column('step', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
    sa.Column('created', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['project.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'project_id', 'step', name='uq_useronboardingflag_user_project_step')
    )
    op.create_index(op.f('ix_useronboardingflag_user_id'), 'useronboardingflag', ['user_id'], unique=False)
    op.create_table('feedback',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
    sa.Column('message', sqlmodel.sql.sqltypes.AutoString(length=5000), nullable=False),
    sa.Column('page', sqlmodel.sql.sqltypes.AutoString(length=2048), nullable=True),
    sa.Column('created', sa.DateTime(), nullable=False),
    sa.Column('resolved', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_feedback_user_id'), 'feedback', ['user_id'], unique=False)
    op.add_column('user', sa.Column('email_verified_at', sa.DateTime(), nullable=True))
    op.create_table('useremailverification',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('code_hash', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
    sa.Column('created', sa.DateTime(), nullable=False),
    sa.Column('expires', sa.DateTime(), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id')
    )
    op.create_table('projectdvcpush',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('created', sa.DateTime(), nullable=False),
    sa.Column('updated', sa.DateTime(), nullable=False),
    sa.Column('n_files', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['project.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_projectdvcpush_project_id'), 'projectdvcpush', ['project_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_projectdvcpush_project_id'), table_name='projectdvcpush')
    op.drop_table('projectdvcpush')
    op.drop_table('useremailverification')
    op.drop_column('user', 'email_verified_at')
    op.drop_index(op.f('ix_feedback_user_id'), table_name='feedback')
    op.drop_table('feedback')
    op.drop_index(op.f('ix_useronboardingflag_user_id'), table_name='useronboardingflag')
    op.drop_table('useronboardingflag')
