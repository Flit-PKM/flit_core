"""Add user_encryption_keys table and encryption_version to notes and chunks.

Revision ID: add_encryption_at_rest
Revises: 001_plan_subs
Create Date: Encryption at rest (Option A): per-user DEK table and version columns

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_encryption_at_rest"
down_revision: Union[str, Sequence[str], None] = "001_plan_subs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_encryption_keys",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("encrypted_dek", sa.Text(), nullable=False),
        sa.Column("key_version", sa.SmallInteger(), nullable=False, server_default=sa.text("1")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_index(
        op.f("ix_user_encryption_keys_user_id"),
        "user_encryption_keys",
        ["user_id"],
        unique=False,
    )

    op.add_column(
        "notes",
        sa.Column("encryption_version", sa.SmallInteger(), nullable=True),
    )
    op.add_column(
        "chunks",
        sa.Column("encryption_version", sa.SmallInteger(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("chunks", "encryption_version")
    op.drop_column("notes", "encryption_version")
    op.drop_index(op.f("ix_user_encryption_keys_user_id"), table_name="user_encryption_keys")
    op.drop_table("user_encryption_keys")
