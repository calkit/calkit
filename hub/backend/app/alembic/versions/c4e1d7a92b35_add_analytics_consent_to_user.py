"""Add analytics consent to user

Revision ID: c4e1d7a92b35
Revises: 97762605447f

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c4e1d7a92b35'
down_revision = '97762605447f'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'user', sa.Column('analytics_consent', sa.Boolean(), nullable=True)
    )


def downgrade():
    op.drop_column('user', 'analytics_consent')
