"""Add feedbacks table.

Revision ID: add_feedbacks
Revises: add_access_codes
Create Date: User feedback submissions (public POST, superuser read/delete)

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_feedbacks"
down_revision: Union[str, Sequence[str], None] = "add_access_codes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create feedbacks table."""
    op.create_table(
        "feedbacks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feedbacks")),
    )
    op.create_index(op.f("ix_feedbacks_id"), "feedbacks", ["id"], unique=False)
    op.create_index(
        op.f("ix_feedbacks_created_at"), "feedbacks", ["created_at"], unique=False
    )


def downgrade() -> None:
    """Drop feedbacks table."""
    op.drop_index(op.f("ix_feedbacks_created_at"), table_name="feedbacks")
    op.drop_index(op.f("ix_feedbacks_id"), table_name="feedbacks")
    op.drop_table("feedbacks")
