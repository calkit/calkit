"""Add S3 storage connections

Revision ID: fd037aba1389
Revises: 56dfc88b0e4c

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = 'fd037aba1389'
down_revision = '56dfc88b0e4c'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'storageresource',
        sa.Column('credential_id', sa.Uuid(), nullable=True),
    )
    op.add_column(
        'storageresource',
        sa.Column(
            'region',
            sqlmodel.sql.sqltypes.AutoString(length=64),
            nullable=True,
        ),
    )
    op.add_column(
        'storageresource',
        sa.Column(
            'read_only',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index(
        op.f('ix_storageresource_credential_id'),
        'storageresource',
        ['credential_id'],
        unique=False,
    )
    op.create_foreign_key(
        'storageresource_credential_id_fkey',
        'storageresource',
        'userexternalcredential',
        ['credential_id'],
        ['id'],
        ondelete='CASCADE',
    )


def downgrade():
    op.drop_constraint(
        'storageresource_credential_id_fkey',
        'storageresource',
        type_='foreignkey',
    )
    op.drop_index(
        op.f('ix_storageresource_credential_id'),
        table_name='storageresource',
    )
    op.drop_column('storageresource', 'read_only')
    op.drop_column('storageresource', 'region')
    op.drop_column('storageresource', 'credential_id')
