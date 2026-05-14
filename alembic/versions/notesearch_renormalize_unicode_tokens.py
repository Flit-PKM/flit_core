"""Re-normalize notesearch content after Unicode tokenization change.

Revision ID: notesearch_renormalize_unicode
Revises: users_password_hash_nullable
Create Date: 2026-05-14

"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "notesearch_renormalize_unicode"
down_revision: Union[str, Sequence[str], None] = "users_password_hash_nullable"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Rebuild notesearch.content from note title/body for plaintext, non-deleted notes."""
    from service.notesearch import normalize_for_search

    conn = op.get_bind()
    result = conn.execute(
        text(
            "SELECT n.id, n.title, n.content FROM notes n "
            "INNER JOIN notesearch ns ON ns.note_id = n.id "
            "WHERE NOT n.is_deleted AND n.encryption_version IS NULL"
        )
    )
    rows = result.fetchall()
    for row in rows:
        note_id, title, content = row
        title = title or ""
        content = content or ""
        normalized = normalize_for_search(title, content)
        conn.execute(
            text(
                "UPDATE notesearch SET content = :content WHERE note_id = :note_id"
            ),
            {"content": normalized, "note_id": note_id},
        )


def downgrade() -> None:
    """Cannot restore previous tokenization; no-op."""
