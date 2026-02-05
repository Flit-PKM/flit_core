"""Add superusers table and move is_superuser off users.

Revision ID: add_superusers_table
Revises: add_subscriptions
Create Date: 2026-02-02

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision: str = "add_superusers_table"
down_revision: Union[str, Sequence[str], None] = "add_subscriptions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create superusers table, backfill from users.is_superuser, drop column."""
    op.create_table(
        "superusers",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("granted_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("granted_by", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_superusers_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["granted_by"],
            ["users.id"],
            name=op.f("fk_superusers_granted_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_superusers")),
    )
    op.create_index(
        op.f("ix_superusers_user_id"),
        "superusers",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_superusers_granted_by"),
        "superusers",
        ["granted_by"],
        unique=False,
    )

    # Backfill: insert rows for users who currently have is_superuser = true
    conn = op.get_bind()
    result = conn.execute(
        text("""
            SELECT EXISTS (
                SELECT FROM information_schema.columns
                WHERE table_schema = 'public'
                AND table_name = 'users'
                AND column_name = 'is_superuser'
            );
        """)
    )
    if result.scalar():
        conn.execute(
            text("""
                INSERT INTO superusers (user_id, granted_at)
                SELECT id, NOW() FROM users WHERE is_superuser = true
            """)
        )
        op.drop_column("users", "is_superuser")


def downgrade() -> None:
    """Restore users.is_superuser and drop superusers table."""
    op.add_column(
        "users",
        sa.Column("is_superuser", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    conn = op.get_bind()
    conn.execute(
        text("""
            UPDATE users u
            SET is_superuser = true
            WHERE EXISTS (SELECT 1 FROM superusers s WHERE s.user_id = u.id)
        """)
    )
    op.drop_index(op.f("ix_superusers_granted_by"), table_name="superusers")
    op.drop_index(op.f("ix_superusers_user_id"), table_name="superusers")
    op.drop_table("superusers")
