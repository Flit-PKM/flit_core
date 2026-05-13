"""Dodo webhook idempotency table (processed_dodo_webhooks).

Revision ID: add_processed_dodo_webhooks
Revises: last_login_backfill_not_null
Create Date: 2026-05-12

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "add_processed_dodo_webhooks"
down_revision: Union[str, Sequence[str], None] = "last_login_backfill_not_null"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "processed_dodo_webhooks",
        sa.Column("webhook_id", sa.String(length=512), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("webhook_id", name=op.f("pk_processed_dodo_webhooks")),
    )


def downgrade() -> None:
    op.drop_table("processed_dodo_webhooks")
