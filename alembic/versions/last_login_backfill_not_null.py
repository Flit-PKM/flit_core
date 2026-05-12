"""Backfill users.last_login from activity updated_at; set NOT NULL.

Revision ID: last_login_backfill_not_null
Revises: last_login_timestamp_naive_utc
Create Date: 2026-05-11

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "last_login_backfill_not_null"
down_revision: Union[str, Sequence[str], None] = "last_login_timestamp_naive_utc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_BACKFILL_SQL = """
UPDATE users AS u
SET last_login = sub.g
FROM (
    SELECT
        u2.id,
        GREATEST(
            u2.created_at,
            u2.updated_at,
            COALESCE(act.mx, u2.created_at),
            COALESCE(u2.last_login, u2.created_at)
        ) AS g
    FROM users u2
    LEFT JOIN (
        SELECT z.user_id, MAX(z.ts) AS mx
        FROM (
            SELECT user_id, updated_at AS ts FROM notes WHERE NOT is_deleted
            UNION ALL
            SELECT user_id, updated_at FROM categories WHERE NOT is_deleted
            UNION ALL
            SELECT user_id, updated_at FROM connected_apps
            UNION ALL
            SELECT user_id, updated_at FROM plan_subscriptions
            UNION ALL
            SELECT n.user_id AS user_id, nc.updated_at AS ts
            FROM note_categories nc
            INNER JOIN notes n ON n.id = nc.note_id
            WHERE NOT nc.is_deleted AND NOT n.is_deleted
            UNION ALL
            SELECT n.user_id AS user_id, ch.updated_at AS ts
            FROM chunks ch
            INNER JOIN notes n ON n.id = ch.note_id
            WHERE NOT ch.is_deleted AND NOT n.is_deleted
        ) z
        GROUP BY z.user_id
    ) act ON act.user_id = u2.id
) AS sub
WHERE u.id = sub.id
"""


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(sa.text(_BACKFILL_SQL))
    op.execute(sa.text("ALTER TABLE users ALTER COLUMN last_login SET NOT NULL"))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(sa.text("ALTER TABLE users ALTER COLUMN last_login DROP NOT NULL"))
