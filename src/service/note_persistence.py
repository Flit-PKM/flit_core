"""Single place where note rows are written to the DB and notesearch is updated.

All note INSERT/UPDATE/soft-delete goes through this layer so notesearch stays in sync.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from models.note import Note
from service.notesearch import delete_notesearch, upsert_notesearch


async def insert_note(
    session: AsyncSession,
    note: Note,
    *,
    plaintext_title: str,
    plaintext_content: str,
    encryption_enabled: bool,
) -> Note:
    """Add a new note to the DB, then update notesearch if not encrypted."""
    session.add(note)
    await session.flush()
    await session.refresh(note)
    if not encryption_enabled:
        await upsert_notesearch(
            session,
            note.id,
            note.user_id,
            plaintext_title,
            plaintext_content,
        )
    return note


async def update_note(
    session: AsyncSession,
    note: Note,
    *,
    plaintext_title: str,
    plaintext_content: str,
    encryption_enabled: bool,
) -> Note:
    """Flush and refresh an already-modified note, then update notesearch if not encrypted."""
    await session.flush()
    await session.refresh(note)
    if not encryption_enabled:
        await upsert_notesearch(
            session,
            note.id,
            note.user_id,
            plaintext_title,
            plaintext_content,
        )
    return note


async def soft_delete_note(
    session: AsyncSession,
    note: Note,
    *,
    version: int | None = None,
) -> None:
    """Soft-delete a note and hard-delete its notesearch row if present.
    If version is set (e.g. from sync), use it; otherwise increment version.
    """
    note.is_deleted = True
    if version is not None:
        note.version = version
    else:
        note.version += 1
    await session.flush()
    await delete_notesearch(session, note.id)
