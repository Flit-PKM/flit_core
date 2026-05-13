"""Allow NULL password_hash for Google Sign-In-only users.

Revision ID: users_password_hash_nullable
Revises: add_processed_dodo_webhooks
Create Date: 2026-05-13

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "users_password_hash_nullable"
down_revision: Union[str, Sequence[str], None] = "add_processed_dodo_webhooks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "users",
        "password_hash",
        existing_type=sa.String(),
        nullable=True,
    )


def downgrade() -> None:
    # Fails if any row has password_hash NULL; remove or backfill those users first.
    op.alter_column(
        "users",
        "password_hash",
        existing_type=sa.String(),
        nullable=False,
    )
