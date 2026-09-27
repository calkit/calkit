"""Add external storage resources

Revision ID: 56dfc88b0e4c
Revises: c4e1d7a92b35

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = '56dfc88b0e4c'
down_revision = 'c4e1d7a92b35'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'storageresource',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('owner_account_id', sa.Uuid(), nullable=False),
        sa.Column(
            'name',
            sqlmodel.sql.sqltypes.AutoString(length=64),
            nullable=False,
        ),
        sa.Column(
            'kind',
            sqlmodel.sql.sqltypes.AutoString(length=32),
            nullable=False,
        ),
        sa.Column(
            'bucket',
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=False,
        ),
        sa.Column('credential_user_id', sa.Uuid(), nullable=False),
        sa.Column('created', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['owner_account_id'], ['account.id']),
        sa.ForeignKeyConstraint(['credential_user_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'owner_account_id',
            'name',
            name='uq_storageresource_owner_account_name',
        ),
    )
    op.create_index(
        op.f('ix_storageresource_owner_account_id'),
        'storageresource',
        ['owner_account_id'],
        unique=False,
    )
    op.add_column(
        'project', sa.Column('dvc_storage_id', sa.Uuid(), nullable=True)
    )
    op.create_foreign_key(
        'project_dvc_storage_id_fkey',
        'project',
        'storageresource',
        ['dvc_storage_id'],
        ['id'],
    )
    op.create_table(
        'projectstoragehistory',
        sa.Column('project_id', sa.Uuid(), nullable=False),
        sa.Column('storage_resource_id', sa.Uuid(), nullable=False),
        sa.Column('first_used', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['project.id']),
        sa.ForeignKeyConstraint(
            ['storage_resource_id'], ['storageresource.id']
        ),
        sa.PrimaryKeyConstraint('project_id', 'storage_resource_id'),
    )


def downgrade():
    op.drop_table('projectstoragehistory')
    op.drop_constraint(
        'project_dvc_storage_id_fkey', 'project', type_='foreignkey'
    )
    op.drop_column('project', 'dvc_storage_id')
    op.drop_index(
        op.f('ix_storageresource_owner_account_id'),
        table_name='storageresource',
    )
    op.drop_table('storageresource')
