"""Add access_codes and access_code_grants tables.

Revision ID: add_access_codes
Revises: add_plan_sub_product_id
Create Date: Time-limited access codes for Core+AI / Core+AI+Encryption

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_access_codes"
down_revision: Union[str, Sequence[str], None] = "add_plan_sub_product_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "access_codes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(length=64), nullable=False, unique=True),
        sa.Column("period_weeks", sa.Integer(), nullable=False),
        sa.Column("includes_encryption", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_access_codes_code", "access_codes", ["code"], unique=True)

    op.create_table(
        "access_code_grants",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("access_code_id", sa.Integer(), sa.ForeignKey("access_codes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("includes_encryption", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_access_code_grants_user_id", "access_code_grants", ["user_id"])
    op.create_index("ix_access_code_grants_expires_at", "access_code_grants", ["expires_at"])


def downgrade() -> None:
    op.drop_table("access_code_grants")
    op.drop_table("access_codes")
