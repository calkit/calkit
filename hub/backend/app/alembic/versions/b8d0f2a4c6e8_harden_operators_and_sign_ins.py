"""Harden Operators and sign-ins

Revision ID: b8d0f2a4c6e8
Revises: a7c9e1b3d5f7
Create Date: 2026-10-19 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = 'b8d0f2a4c6e8'
down_revision = 'a7c9e1b3d5f7'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('operator', sa.Column('public_key', sa.JSON(), nullable=True))
    op.add_column('operator', sa.Column('cli_token_requested_at', sa.DateTime(), nullable=True))
    op.add_column('usertoken', sa.Column('operator_id', sa.Uuid(), nullable=True))
    op.create_foreign_key('usertoken_operator_id_fkey', 'usertoken', 'operator', ['operator_id'], ['id'], ondelete='CASCADE')
    op.add_column('usertotp', sa.Column('setup_session_id', sa.Uuid(), nullable=True))
    op.add_column('usertotp', sa.Column('lockouts', sa.Integer(), server_default='0', nullable=False))
    op.add_column('refreshtoken', sa.Column('rotated_at', sa.DateTime(), nullable=True))
    op.create_table('userdailycount',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
    sa.Column('day', sa.Date(), nullable=False),
    sa.Column('count', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'kind')
    )
    # Deleting a user takes their Operators and authenticator with them
    op.drop_constraint('operator_user_id_fkey', 'operator', type_='foreignkey')
    op.create_foreign_key('operator_user_id_fkey', 'operator', 'user', ['user_id'], ['id'], ondelete='CASCADE')
    op.drop_constraint('usertotp_user_id_fkey', 'usertotp', type_='foreignkey')
    op.create_foreign_key('usertotp_user_id_fkey', 'usertotp', 'user', ['user_id'], ['id'], ondelete='CASCADE')


def downgrade():
    op.drop_constraint('usertotp_user_id_fkey', 'usertotp', type_='foreignkey')
    op.create_foreign_key('usertotp_user_id_fkey', 'usertotp', 'user', ['user_id'], ['id'])
    op.drop_constraint('operator_user_id_fkey', 'operator', type_='foreignkey')
    op.create_foreign_key('operator_user_id_fkey', 'operator', 'user', ['user_id'], ['id'])
    op.drop_table('userdailycount')
    op.drop_column('refreshtoken', 'rotated_at')
    op.drop_column('usertotp', 'lockouts')
    op.drop_column('usertotp', 'setup_session_id')
    op.drop_constraint('usertoken_operator_id_fkey', 'usertoken', type_='foreignkey')
    op.drop_column('usertoken', 'operator_id')
    op.drop_column('operator', 'cli_token_requested_at')
    op.drop_column('operator', 'public_key')
