from __future__ import annotations

from typing import List

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import NotFoundError, ConflictError
from logging_config import get_logger
from models.note import Note
from models.relationship import Relationship
from schemas.relationship import RelationshipCreate

logger = get_logger(__name__)


async def _ensure_note_exists(session: AsyncSession, note_id: int) -> None:
    result = await session.execute(select(Note).where(Note.id == note_id))
    if not result.scalar_one_or_none():
        raise NotFoundError(f"Note not found: id={note_id}")


async def create_relationship(
    session: AsyncSession,
    data: RelationshipCreate,
) -> Relationship:
    await _ensure_note_exists(session, data.note_a_id)
    await _ensure_note_exists(session, data.note_b_id)
    rel = Relationship(
        note_a_id=data.note_a_id,
        note_b_id=data.note_b_id,
        type=data.type,
    )
    session.add(rel)
    try:
        await session.flush()
        await session.refresh(rel)
    except IntegrityError:
        await session.rollback()
        raise ConflictError("Relationship between these notes already exists") from None
    logger.info(
        "Relationship created: note_a=%s, note_b=%s, type=%s",
        data.note_a_id,
        data.note_b_id,
        data.type,
    )
    return rel


async def get_relationship(
    session: AsyncSession,
    note_a_id: int,
    note_b_id: int,
) -> Relationship | None:
    """Get an active (non-deleted) relationship by note_a_id and note_b_id."""
    result = await session.execute(
        select(Relationship).where(
            Relationship.note_a_id == note_a_id,
            Relationship.note_b_id == note_b_id,
            Relationship.is_deleted == False,
        )
    )
    return result.scalar_one_or_none()


async def get_relationship_or_404(
    session: AsyncSession,
    note_a_id: int,
    note_b_id: int,
) -> Relationship:
    rel = await get_relationship(session, note_a_id, note_b_id)
    if not rel:
        raise NotFoundError("Relationship not found")
    return rel


async def list_relationships_for_note(
    session: AsyncSession,
    note_id: int,
    *,
    skip: int = 0,
    limit: int = 100,
) -> List[Relationship]:
    """List active (non-deleted) relationships involving the given note."""
    result = await session.execute(
        select(Relationship)
        .where(
            or_(
                Relationship.note_a_id == note_id,
                Relationship.note_b_id == note_id,
            ),
            Relationship.is_deleted == False,
        )
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())


async def delete_relationship(
    session: AsyncSession,
    note_a_id: int,
    note_b_id: int,
) -> None:
    """Soft-delete a relationship by note_a_id and note_b_id. Idempotent if already soft-deleted."""
    result = await session.execute(
        select(Relationship).where(
            Relationship.note_a_id == note_a_id,
            Relationship.note_b_id == note_b_id,
        )
    )
    rel = result.scalar_one_or_none()
    if not rel:
        raise NotFoundError("Relationship not found")
    rel.is_deleted = True
    rel.version += 1
    await session.flush()
    logger.info(
        "Relationship soft-deleted: note_a=%s, note_b=%s", note_a_id, note_b_id
    )
