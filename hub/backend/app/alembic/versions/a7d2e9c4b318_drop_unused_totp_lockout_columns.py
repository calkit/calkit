"""Drop unused TOTP lockout columns

Revision ID: a7d2e9c4b318
Revises: ff043cba2b65
Create Date: 2026-10-31 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a7d2e9c4b318'
down_revision = 'ff043cba2b65'
branch_labels = None
depends_on = None


def upgrade():
    # Wrong codes are counted per day in userdailycount instead
    op.drop_column('usertotp', 'lockouts')
    op.drop_column('usertotp', 'locked_until')
    op.drop_column('usertotp', 'failed_attempts')


def downgrade():
    op.add_column('usertotp', sa.Column('failed_attempts', sa.Integer(), server_default='0', nullable=False))
    op.add_column('usertotp', sa.Column('locked_until', sa.DateTime(), nullable=True))
    op.add_column('usertotp', sa.Column('lockouts', sa.Integer(), server_default='0', nullable=False))
