"""Add notesearch table for non-encrypted note search index.

Revision ID: add_notesearch
Revises: rename_feedback_meta
Create Date: notesearch table (note_id, user_id, content)

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

revision: str = "add_notesearch"
down_revision: Union[str, Sequence[str], None] = "rename_feedback_meta"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create notesearch table and backfill from non-encrypted, non-deleted notes."""
    op.create_table(
        "notesearch",
        sa.Column("note_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["note_id"],
            ["notes.id"],
            name=op.f("fk_notesearch_note_id_notes"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_notesearch_user_id_users"),
        ),
        sa.PrimaryKeyConstraint("note_id", name=op.f("pk_notesearch")),
    )
    op.create_index(
        op.f("ix_notesearch_user_id"),
        "notesearch",
        ["user_id"],
        unique=False,
    )

    # Backfill: only non-encrypted, non-deleted notes (same logic as app)
    from service.notesearch import normalize_for_search

    conn = op.get_bind()
    result = conn.execute(
        text(
            "SELECT id, user_id, title, content FROM notes "
            "WHERE NOT is_deleted AND encryption_version IS NULL"
        )
    )
    rows = result.fetchall()
    for row in rows:
        note_id, user_id, title, content = row
        title = title or ""
        content = content or ""
        normalized = normalize_for_search(title, content)
        conn.execute(
            text(
                "INSERT INTO notesearch (note_id, user_id, content) "
                "VALUES (:note_id, :user_id, :content)"
            ),
            {"note_id": note_id, "user_id": user_id, "content": normalized},
        )


def downgrade() -> None:
    """Drop notesearch table."""
    op.drop_index(op.f("ix_notesearch_user_id"), table_name="notesearch")
    op.drop_table("notesearch")
