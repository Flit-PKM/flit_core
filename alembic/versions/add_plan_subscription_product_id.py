"""Add product_id to plan_subscriptions.

Revision ID: add_plan_sub_product_id
Revises: add_encryption_at_rest
Create Date: Plan subscription product_id for encryption-plan gating

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_plan_sub_product_id"
down_revision: Union[str, Sequence[str], None] = "add_encryption_at_rest"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "plan_subscriptions",
        sa.Column("product_id", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("plan_subscriptions", "product_id")
