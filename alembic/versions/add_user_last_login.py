"""Add users.last_login for engagement stats and prune.

Revision ID: add_user_last_login
Revises: add_note_pinned_color
Create Date: 2026-05-11

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "add_user_last_login"
down_revision: Union[str, Sequence[str], None] = "add_note_pinned_color"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("last_login", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "last_login")
