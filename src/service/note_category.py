from __future__ import annotations

from typing import List

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import NotFoundError, ConflictError
from logging_config import get_logger
from models.category import Category
from models.note import Note
from models.note_category import NoteCategory
from schemas.note_category import NoteCategoryCreate

logger = get_logger(__name__)


async def _ensure_note_exists(session: AsyncSession, note_id: int) -> None:
    result = await session.execute(select(Note).where(Note.id == note_id))
    if not result.scalar_one_or_none():
        raise NotFoundError("Note not found")


async def _ensure_category_exists(session: AsyncSession, category_id: int) -> None:
    result = await session.execute(select(Category).where(Category.id == category_id))
    if not result.scalar_one_or_none():
        raise NotFoundError("Category not found")


async def link_note_category(
    session: AsyncSession,
    data: NoteCategoryCreate,
) -> NoteCategory:
    await _ensure_note_exists(session, data.note_id)
    await _ensure_category_exists(session, data.category_id)
    link = NoteCategory(note_id=data.note_id, category_id=data.category_id)
    session.add(link)
    try:
        await session.flush()
        await session.refresh(link)
    except IntegrityError:
        await session.rollback()
        raise ConflictError("Note already has this category") from None
    logger.info("NoteCategory linked: note_id=%s, category_id=%s", data.note_id, data.category_id)
    return link


async def get_note_category(
    session: AsyncSession,
    note_id: int,
    category_id: int,
) -> NoteCategory | None:
    """Get an active (non-deleted) note-category link by note_id and category_id."""
    result = await session.execute(
        select(NoteCategory).where(
            NoteCategory.note_id == note_id,
            NoteCategory.category_id == category_id,
            NoteCategory.is_deleted == False,
        )
    )
    return result.scalar_one_or_none()


async def unlink_note_category(
    session: AsyncSession,
    note_id: int,
    category_id: int,
) -> None:
    """Soft-delete a note-category link. Idempotent if already soft-deleted."""
    result = await session.execute(
        select(NoteCategory).where(
            NoteCategory.note_id == note_id,
            NoteCategory.category_id == category_id,
        )
    )
    link = result.scalar_one_or_none()
    if not link:
        raise NotFoundError("Note-category link not found")
    link.is_deleted = True
    link.version += 1
    await session.flush()
    logger.info(
        "NoteCategory soft-deleted (unlinked): note_id=%s, category_id=%s",
        note_id,
        category_id,
    )


async def list_categories_for_note(
    session: AsyncSession,
    note_id: int,
) -> List[Category]:
    """List active (non-deleted) categories for a note via active note-category links."""
    result = await session.execute(
        select(Category)
        .join(NoteCategory, NoteCategory.category_id == Category.id)
        .where(
            NoteCategory.note_id == note_id,
            NoteCategory.is_deleted == False,
            Category.is_deleted == False,
        )
    )
    return list(result.scalars().unique().all())


async def list_notes_for_category(
    session: AsyncSession,
    category_id: int,
    *,
    skip: int = 0,
    limit: int = 100,
) -> List[Note]:
    """List active (non-deleted) notes for a category via active note-category links."""
    result = await session.execute(
        select(Note)
        .join(NoteCategory, NoteCategory.note_id == Note.id)
        .where(
            NoteCategory.category_id == category_id,
            NoteCategory.is_deleted == False,
            Note.is_deleted == False,
        )
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().unique().all())
