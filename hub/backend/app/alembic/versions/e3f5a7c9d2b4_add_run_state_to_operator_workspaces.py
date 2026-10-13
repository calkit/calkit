"""Add run state to operator workspaces

Revision ID: e3f5a7c9d2b4
Revises: d8e2f4a6b1c3
Create Date: 2026-09-29 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e3f5a7c9d2b4'
down_revision = 'd8e2f4a6b1c3'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('operatorworkspace', sa.Column('run_state', sa.JSON(), server_default='{}', nullable=False))


def downgrade():
    op.drop_column('operatorworkspace', 'run_state')
