"""Add subscriptions table (email list).

Revision ID: add_subscriptions
Revises: 001_color_scheme
Create Date: 2026-02-02

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_subscriptions"
down_revision: Union[str, Sequence[str], None] = "001_color_scheme"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create subscriptions table."""
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_subscriptions")),
    )
    op.create_index(op.f("ix_subscriptions_id"), "subscriptions", ["id"], unique=False)
    op.create_index(op.f("ix_subscriptions_email"), "subscriptions", ["email"], unique=True)


def downgrade() -> None:
    """Drop subscriptions table."""
    op.drop_index(op.f("ix_subscriptions_email"), table_name="subscriptions")
    op.drop_index(op.f("ix_subscriptions_id"), table_name="subscriptions")
    op.drop_table("subscriptions")
