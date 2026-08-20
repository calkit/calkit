"""Add user onboarding flags

Revision ID: 97762605447f
Revises: a333fc5aa994
Create Date: 2026-08-20 03:05:51.669601

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


def downgrade():
    op.drop_index(op.f('ix_useronboardingflag_user_id'), table_name='useronboardingflag')
    op.drop_table('useronboardingflag')
