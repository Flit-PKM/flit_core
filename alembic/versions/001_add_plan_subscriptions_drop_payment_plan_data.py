"""Add plan_subscriptions table and drop users.payment_plan_data.

Revision ID: 001_plan_subs
Revises:
Create Date: 2025-02-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "001_plan_subs"
down_revision: Union[str, None] = "add_user_payment_plan_data"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "plan_subscriptions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("dodo_subscription_id", sa.String(length=255), nullable=False),
        sa.Column("dodo_customer_id", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=False), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=False), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_plan_subscriptions_id", "plan_subscriptions", ["id"], unique=False)
    op.create_index("ix_plan_subscriptions_user_id", "plan_subscriptions", ["user_id"], unique=True)
    op.create_index("ix_plan_subscriptions_dodo_subscription_id", "plan_subscriptions", ["dodo_subscription_id"], unique=True)
    op.create_index("ix_plan_subscriptions_dodo_customer_id", "plan_subscriptions", ["dodo_customer_id"], unique=False)

    op.drop_column("users", "payment_plan_data")


def downgrade() -> None:
    op.add_column(
        "users",
        sa.Column("payment_plan_data", sa.JSON(), nullable=True),
    )
    op.drop_index("ix_plan_subscriptions_dodo_customer_id", table_name="plan_subscriptions")
    op.drop_index("ix_plan_subscriptions_dodo_subscription_id", table_name="plan_subscriptions")
    op.drop_index("ix_plan_subscriptions_user_id", table_name="plan_subscriptions")
    op.drop_index("ix_plan_subscriptions_id", table_name="plan_subscriptions")
    op.drop_table("plan_subscriptions")
