from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import NotFoundError
from models.note import Note


async def get_note_for_user(
    session: AsyncSession,
    note_id: int,
    user_id: int,
    *,
    include_deleted: bool = False,
) -> Note | None:
    """Load a note by id scoped to user_id; optionally include soft-deleted notes."""
    stmt = select(Note).where(Note.id == note_id, Note.user_id == user_id)
    if not include_deleted:
        stmt = stmt.where(Note.is_deleted == False)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def ensure_active_notes_for_user(
    session: AsyncSession,
    note_ids: list[int],
    user_id: int,
) -> None:
    """Raise NotFoundError if any note id is missing, deleted, or not owned by user_id."""
    unique_ids = list(dict.fromkeys(note_ids))
    if not unique_ids:
        return
    result = await session.execute(
        select(Note.id).where(
            Note.id.in_(unique_ids),
            Note.user_id == user_id,
            Note.is_deleted == False,
        )
    )
    found = {row[0] for row in result.all()}
    for note_id in unique_ids:
        if note_id not in found:
            raise NotFoundError(f"Note not found: id={note_id}")
