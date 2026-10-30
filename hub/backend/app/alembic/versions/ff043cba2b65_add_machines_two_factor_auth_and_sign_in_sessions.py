"""Add machines, two-factor auth, and sign-in sessions

Revision ID: ff043cba2b65
Revises: e6b898df78ed
Create Date: 2026-10-20 18:57:56.555985

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision = 'ff043cba2b65'
down_revision = 'e6b898df78ed'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('machine',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('name', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
    sa.Column('hostname', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
    sa.Column('system_machine_id', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
    sa.Column('platform', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True),
    sa.Column('calkit_version', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True),
    sa.Column('hosts', sa.JSON(), server_default='[]', nullable=False),
    sa.Column('created', sa.DateTime(), nullable=False),
    sa.Column('last_seen', sa.DateTime(), nullable=True),
    sa.Column('mode', sqlmodel.sql.sqltypes.AutoString(length=16), nullable=True),
    sa.Column('connected', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.Column('connect_requested_at', sa.DateTime(), nullable=True),
    sa.Column('restart_pending', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.Column('restart_requested', sa.Boolean(), server_default=sa.false(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('selector', sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
    sa.Column('hashed_verifier', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
    sa.Column('public_key', sa.JSON(), nullable=True),
    sa.Column('cli_token_requested_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_machine_selector'), 'machine', ['selector'], unique=True)
    op.create_index(op.f('ix_machine_user_id'), 'machine', ['user_id'], unique=False)
    # Names are only reserved among active machines
    op.create_index('uq_machine_user_name_active', 'machine', ['user_id', 'name'], unique=True, postgresql_where=sa.text('is_active'))
    op.create_table('machineworkspace',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('machine_id', sa.Uuid(), nullable=False),
    sa.Column('path', sqlmodel.sql.sqltypes.AutoString(length=4096), nullable=False),
    sa.Column('kind', sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
    sa.Column('owner_name', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
    sa.Column('project_name', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
    sa.Column('branch', sqlmodel.sql.sqltypes.AutoString(length=256), nullable=True),
    sa.Column('commit', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True),
    sa.Column('dirty', sa.Boolean(), nullable=True),
    sa.Column('ahead', sa.Integer(), nullable=True),
    sa.Column('behind', sa.Integer(), nullable=True),
    sa.Column('running', sa.Boolean(), nullable=False),
    sa.Column('run_state', sa.JSON(), server_default='{}', nullable=False),
    sa.Column('updated', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['machine_id'], ['machine.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('machine_id', 'path', name='uq_machineworkspace_machine_path')
    )
    op.create_index(op.f('ix_machineworkspace_machine_id'), 'machineworkspace', ['machine_id'], unique=False)
    op.create_index('ix_machineworkspace_project', 'machineworkspace', ['owner_name', 'project_name'], unique=False)
    op.create_table('usertotp',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('secret', sqlmodel.sql.sqltypes.AutoString(length=512), nullable=False),
    sa.Column('setup_session_id', sa.Uuid(), nullable=True),
    sa.Column('created', sa.DateTime(), nullable=False),
    sa.Column('confirmed_at', sa.DateTime(), nullable=True),
    sa.Column('last_verified_at', sa.DateTime(), nullable=True),
    sa.Column('last_used_step', sa.BigInteger(), nullable=True),
    sa.Column('failed_attempts', sa.Integer(), nullable=False),
    sa.Column('locked_until', sa.DateTime(), nullable=True),
    sa.Column('lockouts', sa.Integer(), server_default='0', nullable=False),
    sa.Column('email_code_hash', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True),
    sa.Column('email_code_expires', sa.DateTime(), nullable=True),
    sa.Column('email_code_attempts', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id')
    )
    op.create_table('userdailycount',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('kind', sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
    sa.Column('day', sa.Date(), nullable=False),
    sa.Column('count', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'kind')
    )
    op.add_column('usertoken', sa.Column('machine_id', sa.Uuid(), nullable=True))
    op.create_foreign_key('usertoken_machine_id_fkey', 'usertoken', 'machine', ['machine_id'], ['id'], ondelete='CASCADE')
    op.add_column('refreshtoken', sa.Column('session_id', sa.Uuid(), nullable=True))
    op.add_column('refreshtoken', sa.Column('interactive', sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column('refreshtoken', sa.Column('rotated_at', sa.DateTime(), nullable=True))
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
    op.drop_column('refreshtoken', 'rotated_at')
    op.drop_column('refreshtoken', 'interactive')
    op.drop_column('refreshtoken', 'session_id')
    op.drop_constraint('usertoken_machine_id_fkey', 'usertoken', type_='foreignkey')
    op.drop_column('usertoken', 'machine_id')
    op.drop_table('userdailycount')
    op.drop_table('usertotp')
    op.drop_index('ix_machineworkspace_project', table_name='machineworkspace')
    op.drop_index(op.f('ix_machineworkspace_machine_id'), table_name='machineworkspace')
    op.drop_table('machineworkspace')
    op.drop_index('uq_machine_user_name_active', table_name='machine', postgresql_where=sa.text('is_active'))
    op.drop_index(op.f('ix_machine_user_id'), table_name='machine')
    op.drop_index(op.f('ix_machine_selector'), table_name='machine')
    op.drop_table('machine')
