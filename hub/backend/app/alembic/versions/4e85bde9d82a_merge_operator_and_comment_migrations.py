"""Merge operator and comment migrations

Revision ID: 4e85bde9d82a
Revises: e6b898df78ed, f6a8b0c2d4e5
Create Date: 2026-10-09 18:45:13.922339

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = '4e85bde9d82a'
down_revision = ('e6b898df78ed', 'f6a8b0c2d4e5')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
