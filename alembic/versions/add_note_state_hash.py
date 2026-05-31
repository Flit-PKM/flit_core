"""Add internal state_hash column to notes for efficient updates.

Revision ID: add_note_state_hash
Revises: drop_app_encryption
Create Date: 2026-05-31

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

revision: str = "add_note_state_hash"
down_revision: Union[str, Sequence[str], None] = "drop_app_encryption"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from service.note_state_hash import compute_state_hash

    op.add_column(
        "notes",
        sa.Column("state_hash", sa.String(length=64), nullable=True),
    )

    conn = op.get_bind()
    result = conn.execute(
        text("SELECT id, title, content, pinned, color FROM notes")
    )
    for row in result.fetchall():
        note_id, title, content, pinned, color = row
        state_hash = compute_state_hash(
            title=title or "",
            content=content or "",
            pinned=bool(pinned),
            color=color or "",
        )
        conn.execute(
            text("UPDATE notes SET state_hash = :state_hash WHERE id = :id"),
            {"state_hash": state_hash, "id": note_id},
        )

    op.alter_column("notes", "state_hash", nullable=False)


def downgrade() -> None:
    op.drop_column("notes", "state_hash")
