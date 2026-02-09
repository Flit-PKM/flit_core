from __future__ import annotations

from typing import List

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import NotFoundError
from logging_config import get_logger
from models.category import Category
from models.note import Note
from models.note_category import NoteCategory
from schemas.note import NoteCreate, NoteUpdate
from service.encryption import (
    decrypt_note_fields,
    encrypt_note_fields,
    is_encryption_enabled_for_user,
)

logger = get_logger(__name__)


async def create_note(session: AsyncSession, data: NoteCreate) -> Note:
    dump = data.model_dump()
    if await is_encryption_enabled_for_user(session, data.user_id):
        title_enc, content_enc = await encrypt_note_fields(
            session, data.user_id, dump["title"], dump["content"]
        )
        dump["title"] = title_enc
        dump["content"] = content_enc
        dump["encryption_version"] = 1
    db_note = Note(**dump)
    session.add(db_note)
    await session.flush()
    await session.refresh(db_note)
    if await is_encryption_enabled_for_user(session, db_note.user_id):
        await decrypt_note_fields(session, db_note)
    logger.info("Note created: id=%s, user_id=%s", db_note.id, db_note.user_id)
    return db_note


async def get_note(session: AsyncSession, note_id: int) -> Note | None:
    result = await session.execute(
        select(Note).where(Note.id == note_id, Note.is_deleted == False)
    )
    note = result.scalar_one_or_none()
    if note and await is_encryption_enabled_for_user(session, note.user_id):
        await decrypt_note_fields(session, note)
    return note


async def get_note_or_404(session: AsyncSession, note_id: int) -> Note:
    note = await get_note(session, note_id)
    if not note:
        raise NotFoundError("Note not found")
    return note


async def get_notes_by_user(
    session: AsyncSession,
    user_id: int,
    *,
    skip: int = 0,
    limit: int = 100,
    category_name: str | None = None,
    search: str | None = None,
) -> List[Note]:
    stmt = select(Note).where(
        Note.user_id == user_id,
        Note.is_deleted == False,
    )
    if category_name:
        stmt = (
            stmt.join(NoteCategory, NoteCategory.note_id == Note.id)
            .join(Category, Category.id == NoteCategory.category_id)
            .where(
                Category.user_id == user_id,
                Category.name == category_name,
                Category.is_deleted == False,
                NoteCategory.is_deleted == False,
            )
            .distinct()
        )
    if search and not await is_encryption_enabled_for_user(session, user_id):
        pattern = f"%{search}%"
        stmt = stmt.where(
            or_(
                Note.title.ilike(pattern),
                Note.content.ilike(pattern),
            )
        )
    stmt = stmt.offset(skip).limit(limit)
    result = await session.execute(stmt)
    notes = list(result.scalars().unique().all() if category_name else result.scalars().all())
    if await is_encryption_enabled_for_user(session, user_id):
        for note in notes:
            await decrypt_note_fields(session, note)
    return notes


async def get_all_notes(
    session: AsyncSession,
    *,
    skip: int = 0,
    limit: int = 100,
) -> List[Note]:
    result = await session.execute(
        select(Note).where(Note.is_deleted == False).offset(skip).limit(limit)
    )
    return list(result.scalars().all())


async def update_note(
    session: AsyncSession,
    note_id: int,
    data: NoteUpdate,
) -> Note:
    note = await get_note_or_404(session, note_id)
    payload = data.model_dump(exclude_unset=True)
    if await is_encryption_enabled_for_user(session, note.user_id) and ("title" in payload or "content" in payload):
        title = payload.get("title", note.title)
        content = payload.get("content", note.content)
        title_enc, content_enc = await encrypt_note_fields(
            session, note.user_id, title, content
        )
        payload["title"] = title_enc
        payload["content"] = content_enc
        payload["encryption_version"] = 1
    for field, value in payload.items():
        setattr(note, field, value)
    # Increment version on update
    note.version += 1
    await session.flush()
    await session.refresh(note)
    if await is_encryption_enabled_for_user(session, note.user_id):
        await decrypt_note_fields(session, note)
    logger.info("Note updated: id=%s, version=%s", note_id, note.version)
    return note


async def delete_note(session: AsyncSession, note_id: int, user_id: int) -> None:
    """Soft-delete a note by id and user_id (ownership). Idempotent if already soft-deleted."""
    result = await session.execute(
        select(Note).where(Note.id == note_id, Note.user_id == user_id)
    )
    note = result.scalar_one_or_none()
    if not note:
        raise NotFoundError("Note not found")
    note.is_deleted = True
    note.version += 1
    await session.flush()
    logger.info("Note soft-deleted: id=%s", note_id)
