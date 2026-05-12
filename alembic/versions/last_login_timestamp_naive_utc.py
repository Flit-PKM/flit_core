"""users.last_login: timestamptz -> timestamp without time zone (naive UTC).

Revision ID: last_login_timestamp_naive_utc
Revises: add_admin_extension_tables
Create Date: 2026-05-11

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "last_login_timestamp_naive_utc"
down_revision: Union[str, Sequence[str], None] = "add_admin_extension_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite/offline: tests use create_all from models; no column type change needed here.
        return
    op.execute(
        sa.text(
            "ALTER TABLE users ALTER COLUMN last_login "
            "TYPE TIMESTAMP WITHOUT TIME ZONE "
            "USING (last_login AT TIME ZONE 'UTC')"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(
        sa.text(
            "ALTER TABLE users ALTER COLUMN last_login "
            "TYPE TIMESTAMP WITH TIME ZONE "
            "USING (last_login AT TIME ZONE 'UTC')"
        )
    )
