"""Add restarts to Operators

Revision ID: a7c9e1b3d5f7
Revises: 4e85bde9d82a
Create Date: 2026-10-09 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a7c9e1b3d5f7'
down_revision = '4e85bde9d82a'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('operator', sa.Column('restart_pending', sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column('operator', sa.Column('restart_requested', sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade():
    op.drop_column('operator', 'restart_requested')
    op.drop_column('operator', 'restart_pending')
