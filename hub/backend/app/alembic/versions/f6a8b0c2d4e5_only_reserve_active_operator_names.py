"""Only reserve active Operator names

Revision ID: f6a8b0c2d4e5
Revises: e3f5a7c9d2b4
Create Date: 2026-10-02 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f6a8b0c2d4e5'
down_revision = 'e3f5a7c9d2b4'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint('uq_operator_user_name', 'operator', type_='unique')
    op.create_index('uq_operator_user_name_active', 'operator', ['user_id', 'name'], unique=True, postgresql_where=sa.text('is_active'))


def downgrade():
    op.drop_index('uq_operator_user_name_active', table_name='operator', postgresql_where=sa.text('is_active'))
    op.create_unique_constraint('uq_operator_user_name', 'operator', ['user_id', 'name'])
