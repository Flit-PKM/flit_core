from __future__ import annotations

from datetime import datetime
from typing import List, Literal

from sqlalchemy import asc, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import NotFoundError
from logging_config import get_logger
from models.category import Category
from models.note import Note
from models.note_category import NoteCategory
from schemas.note import NoteCreate, NoteUpdate
from service.note_persistence import flush_note as persistence_flush_note
from service.note_persistence import insert_note as persistence_insert_note
from service.note_persistence import soft_delete_note as persistence_soft_delete_note
from service.relationship import soft_delete_relationships_for_note
from service.note_state_hash import body_hash, compute_state_hash
from service.notesearch import search_notes, upsert_notesearch

logger = get_logger(__name__)

SortByField = Literal["updated_at", "created_at", "title"]
SortOrder = Literal["asc", "desc"]


def _apply_note_filters(
    stmt,
    *,
    user_id: int,
    pinned_only: bool = False,
    updated_after: datetime | None = None,
    updated_before: datetime | None = None,
):
    stmt = stmt.where(Note.user_id == user_id, Note.is_deleted == False)
    if pinned_only:
        stmt = stmt.where(Note.pinned == True)
    if updated_after is not None:
        stmt = stmt.where(Note.updated_at >= updated_after)
    if updated_before is not None:
        stmt = stmt.where(Note.updated_at <= updated_before)
    return stmt


def _apply_sort(
    stmt,
    *,
    sort_by: SortByField = "updated_at",
    sort_order: SortOrder = "desc",
):
    sort_col = {
        "updated_at": Note.updated_at,
        "created_at": Note.created_at,
        "title": Note.title,
    }[sort_by]
    direction = desc if sort_order == "desc" else asc
    return stmt.order_by(Note.pinned.desc(), direction(sort_col))


async def create_note(session: AsyncSession, data: NoteCreate) -> Note:
    dump = data.model_dump()
    plaintext_title = dump["title"]
    plaintext_content = dump["content"]
    db_note = Note(**dump)
    db_note.state_hash = compute_state_hash(
        title=plaintext_title,
        content=plaintext_content,
        pinned=db_note.pinned,
        color=db_note.color,
    )
    await persistence_insert_note(
        session,
        db_note,
        plaintext_title=plaintext_title,
        plaintext_content=plaintext_content,
    )
    logger.info("Note created: id=%s, user_id=%s", db_note.id, db_note.user_id)
    return db_note


async def get_note(session: AsyncSession, note_id: int) -> Note | None:
    result = await session.execute(
        select(Note).where(Note.id == note_id, Note.is_deleted == False)
    )
    return result.scalar_one_or_none()


async def get_note_or_404(
    session: AsyncSession,
    note_id: int,
    user_id: int | None = None,
) -> Note:
    note = await get_note(session, note_id)
    if not note or (user_id is not None and note.user_id != user_id):
        raise NotFoundError("Note not found")
    return note


async def get_notes_by_ids(
    session: AsyncSession,
    user_id: int,
    note_ids: list[int],
) -> list[Note]:
    """Load notes by id for one user, preserving caller order for found ids."""
    if not note_ids:
        return []
    unique_ids = list(dict.fromkeys(note_ids))
    stmt = select(Note).where(
        Note.id.in_(unique_ids),
        Note.user_id == user_id,
        Note.is_deleted == False,
    )
    result = await session.execute(stmt)
    notes = list(result.scalars().all())
    id_to_note = {n.id: n for n in notes}
    return [id_to_note[nid] for nid in note_ids if nid in id_to_note]


async def get_notes_by_user(
    session: AsyncSession,
    user_id: int,
    *,
    skip: int = 0,
    limit: int = 100,
    category_name: str | None = None,
    search: str | None = None,
    pinned_only: bool = False,
    updated_after: datetime | None = None,
    updated_before: datetime | None = None,
    sort_by: SortByField = "updated_at",
    sort_order: SortOrder = "desc",
) -> List[Note]:
    if search:
        return await search_notes(
            session,
            user_id,
            search,
            category_name=category_name,
            skip=skip,
            limit=limit,
            pinned_only=pinned_only,
            updated_after=updated_after,
            updated_before=updated_before,
        )
    stmt = select(Note)
    stmt = _apply_note_filters(
        stmt,
        user_id=user_id,
        pinned_only=pinned_only,
        updated_after=updated_after,
        updated_before=updated_before,
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
    stmt = _apply_sort(stmt, sort_by=sort_by, sort_order=sort_order)
    stmt = stmt.offset(skip).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().unique().all() if category_name else result.scalars().all())


_FINGERPRINT_FIELDS = frozenset({"title", "content", "pinned", "color"})


async def update_note(
    session: AsyncSession,
    note_id: int,
    data: NoteUpdate,
) -> Note:
    note = await get_note_or_404(session, note_id)
    payload = data.model_dump(exclude_unset=True)
    resolved_title = payload.get("title", note.title)
    resolved_content = payload.get("content", note.content)
    resolved_pinned = payload.get("pinned", note.pinned)
    resolved_color = payload.get("color", note.color)

    new_state = compute_state_hash(
        title=resolved_title,
        content=resolved_content,
        pinned=resolved_pinned,
        color=resolved_color,
    )
    other_fields = {k: v for k, v in payload.items() if k not in _FINGERPRINT_FIELDS}
    other_changed = any(getattr(note, k) != v for k, v in other_fields.items())

    if new_state == note.state_hash and not other_changed:
        return note

    body_changed = body_hash(title=resolved_title, content=resolved_content) != body_hash(
        title=note.title, content=note.content
    )

    note.pinned = resolved_pinned
    note.color = resolved_color
    for field, value in other_fields.items():
        setattr(note, field, value)
    if body_changed:
        note.title = resolved_title
        note.content = resolved_content

    note.state_hash = new_state
    note.version += 1
    await persistence_flush_note(session, note)
    if body_changed:
        await upsert_notesearch(
            session,
            note.id,
            note.user_id,
            resolved_title,
            resolved_content,
        )
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
    await soft_delete_relationships_for_note(session, note_id)
    logger.info("Note soft-deleted: id=%s", note_id)
