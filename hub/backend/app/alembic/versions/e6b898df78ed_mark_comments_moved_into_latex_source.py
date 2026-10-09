"""Mark comments moved into LaTeX source

Revision ID: e6b898df78ed
Revises: c4e1d7a92b35

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e6b898df78ed'
down_revision = 'c4e1d7a92b35'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'projectcomment',
        sa.Column('moved_to_source', sa.DateTime(), nullable=True),
    )


def downgrade():
    op.drop_column('projectcomment', 'moved_to_source')
