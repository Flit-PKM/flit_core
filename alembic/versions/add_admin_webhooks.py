"""Add admin_webhooks table for outbound monitoring webhooks.

Revision ID: add_admin_webhooks
Revises: mcp_connections
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "add_admin_webhooks"
down_revision: Union[str, Sequence[str], None] = "mcp_connections"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "admin_webhooks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("secret", sa.Text(), nullable=True),
        sa.Column("events", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_admin_webhooks_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admin_webhooks")),
    )
    op.create_index(op.f("ix_admin_webhooks_id"), "admin_webhooks", ["id"], unique=False)
    op.create_index(
        op.f("ix_admin_webhooks_created_by"),
        "admin_webhooks",
        ["created_by"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_admin_webhooks_created_by"), table_name="admin_webhooks")
    op.drop_index(op.f("ix_admin_webhooks_id"), table_name="admin_webhooks")
    op.drop_table("admin_webhooks")
