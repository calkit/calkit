"""Lowercase account names and add display_name

Revision ID: af024967630d
Revises: c1f9a3e27d48
Create Date: 2026-04-15 12:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "af024967630d"
down_revision = "c1f9a3e27d48"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "account",
        sa.Column("display_name", sa.String(length=64), nullable=True),
    )
    conn = op.get_bind()
    collisions = conn.execute(
        sa.text(
            "SELECT lower(name) AS lname, array_agg(name) AS names "
            "FROM account GROUP BY lower(name) HAVING count(*) > 1"
        )
    ).fetchall()
    if collisions:
        raise RuntimeError(
            "Cannot lowercase account.name: case-insensitive collisions "
            f"exist: {collisions}. Resolve these rows before re-running."
        )
    # For org accounts, pull the nicely-cased display_name from the org row
    # (account.name was already lowercased on org creation). For user accounts,
    # the existing account.name preserves whatever casing the user signed up
    # with.
    conn.execute(
        sa.text(
            "UPDATE account SET display_name = COALESCE("
            "(SELECT display_name FROM org WHERE org.id = account.org_id), "
            "name) "
            "WHERE display_name IS NULL"
        )
    )
    conn.execute(sa.text("UPDATE account SET name = lower(name)"))
    op.create_check_constraint(
        "ck_account_name_lowercase", "account", "name = lower(name)"
    )
    op.drop_column("org", "display_name")


def downgrade():
    op.add_column(
        "org",
        sa.Column("display_name", sa.String(length=255), nullable=True),
    )
    op.execute(
        "UPDATE org SET display_name = account.display_name "
        "FROM account WHERE account.org_id = org.id"
    )
    op.alter_column("org", "display_name", nullable=False)
    op.drop_constraint("ck_account_name_lowercase", "account", type_="check")
    op.drop_column("account", "display_name")
