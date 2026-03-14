from __future__ import annotations

from typing import List

from sqlalchemy import select
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
from service.note_persistence import insert_note as persistence_insert_note
from service.note_persistence import soft_delete_note as persistence_soft_delete_note
from service.note_persistence import update_note as persistence_update_note
from service.notesearch import search_notes

logger = get_logger(__name__)


async def create_note(session: AsyncSession, data: NoteCreate) -> Note:
    dump = data.model_dump()
    plaintext_title = dump["title"]
    plaintext_content = dump["content"]
    encryption_enabled = await is_encryption_enabled_for_user(session, data.user_id)
    if encryption_enabled:
        title_enc, content_enc = await encrypt_note_fields(
            session, data.user_id, plaintext_title, plaintext_content
        )
        dump["title"] = title_enc
        dump["content"] = content_enc
        dump["encryption_version"] = 1
    db_note = Note(**dump)
    await persistence_insert_note(
        session,
        db_note,
        plaintext_title=plaintext_title,
        plaintext_content=plaintext_content,
        encryption_enabled=encryption_enabled,
    )
    if encryption_enabled:
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
    encryption_enabled = await is_encryption_enabled_for_user(session, user_id)
    if search and not encryption_enabled:
        notes = await search_notes(
            session,
            user_id,
            search,
            category_name=category_name,
            skip=skip,
            limit=limit,
        )
        return notes
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
    stmt = stmt.order_by(Note.updated_at.desc()).offset(skip).limit(limit)
    result = await session.execute(stmt)
    notes = list(result.scalars().unique().all() if category_name else result.scalars().all())
    if encryption_enabled:
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
    encryption_enabled = await is_encryption_enabled_for_user(session, note.user_id)
    if encryption_enabled and ("title" in payload or "content" in payload):
        title = payload.get("title", note.title)
        content = payload.get("content", note.content)
        title_enc, content_enc = await encrypt_note_fields(
            session, note.user_id, title, content
        )
        payload["title"] = title_enc
        payload["content"] = content_enc
        payload["encryption_version"] = 1
        plaintext_title, plaintext_content = title, content
    else:
        plaintext_title = payload.get("title", note.title)
        plaintext_content = payload.get("content", note.content)
    for field, value in payload.items():
        setattr(note, field, value)
    note.version += 1
    await persistence_update_note(
        session,
        note,
        plaintext_title=plaintext_title,
        plaintext_content=plaintext_content,
        encryption_enabled=encryption_enabled,
    )
    if encryption_enabled:
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
    await persistence_soft_delete_note(session, note)
    logger.info("Note soft-deleted: id=%s", note_id)
