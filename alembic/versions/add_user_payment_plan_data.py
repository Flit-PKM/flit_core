"""Add users.payment_plan_data JSON column for payment plan tracking.

Revision ID: add_user_payment_plan_data
Revises: add_superusers_table
Create Date: 2026-02-02

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_user_payment_plan_data"
down_revision: Union[str, Sequence[str], None] = "add_superusers_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add payment_plan_data JSON column to users."""
    op.add_column(
        "users",
        sa.Column(
            "payment_plan_data",
            sa.JSON(),
            nullable=True,
            comment="JSON data for payment plan tracking; visible to the user",
        ),
    )


def downgrade() -> None:
    """Remove payment_plan_data column from users."""
    op.drop_column("users", "payment_plan_data")
