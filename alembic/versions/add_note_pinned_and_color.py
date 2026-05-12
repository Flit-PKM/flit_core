"""Add pinned and color fields to notes.

Revision ID: add_note_pinned_color
Revises: add_notesearch
Create Date: 2026-05-11

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "add_note_pinned_color"
down_revision: Union[str, Sequence[str], None] = "add_notesearch"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add note display metadata with defaults for existing rows."""
    op.add_column(
        "notes",
        sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "notes",
        sa.Column("color", sa.String(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    """Remove note display metadata."""
    op.drop_column("notes", "color")
    op.drop_column("notes", "pinned")
