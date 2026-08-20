"""Add feedback table

Revision ID: ac827fc78902
Revises: 97762605447f

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = 'ac827fc78902'
down_revision = '97762605447f'
branch_labels = None
depends_on = None


def upgrade():
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


def downgrade():
    op.drop_index(op.f('ix_feedback_user_id'), table_name='feedback')
    op.drop_table('feedback')
