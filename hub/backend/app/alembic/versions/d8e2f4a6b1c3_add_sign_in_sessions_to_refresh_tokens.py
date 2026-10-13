"""Add sign-in sessions to refresh tokens

Revision ID: d8e2f4a6b1c3
Revises: cc224455e0bb
Create Date: 2026-09-27 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd8e2f4a6b1c3'
down_revision = 'cc224455e0bb'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('refreshtoken', sa.Column('session_id', sa.Uuid(), nullable=True))
    op.add_column('refreshtoken', sa.Column('interactive', sa.Boolean(), server_default=sa.false(), nullable=False))
    op.create_index(op.f('ix_refreshtoken_session_id'), 'refreshtoken', ['session_id'], unique=False)
    # Sign-ins from before sessions were recorded, so people already signed
    # in aren't refused: web ones are known by how their tokens are
    # described, and each gets a session of its own, which rotations carry
    op.execute(
        "UPDATE refreshtoken SET interactive = true "
        "WHERE description IN ('password login', 'GitHub login', 'Google login')"
    )
    op.execute("UPDATE refreshtoken SET session_id = id WHERE session_id IS NULL")


def downgrade():
    op.drop_index(op.f('ix_refreshtoken_session_id'), table_name='refreshtoken')
    op.drop_column('refreshtoken', 'interactive')
    op.drop_column('refreshtoken', 'session_id')
