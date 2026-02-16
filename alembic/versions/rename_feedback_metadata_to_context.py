"""Rename feedbacks.metadata to context.

Revision ID: rename_feedback_meta
Revises: add_feedbacks
Create Date: Rename metadata column to context

"""
from typing import Sequence, Union

from alembic import op


revision: str = "rename_feedback_meta"
down_revision: Union[str, Sequence[str], None] = "add_feedbacks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Rename metadata column to context."""
    op.alter_column(
        "feedbacks",
        "metadata",
        new_column_name="context",
    )


def downgrade() -> None:
    """Rename context column back to metadata."""
    op.alter_column(
        "feedbacks",
        "context",
        new_column_name="metadata",
    )
