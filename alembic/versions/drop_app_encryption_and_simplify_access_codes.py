"""Drop application-level encryption tables/columns and access-code encryption flag.

Revision ID: drop_app_encryption
Revises: mcp_oauth_dcr
Create Date: 2026-05-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "drop_app_encryption"
down_revision: Union[str, Sequence[str], None] = "mcp_oauth_dcr"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index(op.f("ix_user_encryption_keys_user_id"), table_name="user_encryption_keys")
    op.drop_table("user_encryption_keys")
    op.drop_column("notes", "encryption_version")
    op.drop_column("chunks", "encryption_version")
    op.drop_column("access_codes", "includes_encryption")
    op.drop_column("access_code_grants", "includes_encryption")


def downgrade() -> None:
    op.add_column(
        "access_code_grants",
        sa.Column("includes_encryption", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "access_codes",
        sa.Column("includes_encryption", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "chunks",
        sa.Column("encryption_version", sa.SmallInteger(), nullable=True),
    )
    op.add_column(
        "notes",
        sa.Column("encryption_version", sa.SmallInteger(), nullable=True),
    )
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
