from __future__ import annotations

from typing import List

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import AuthorizationError, NotFoundError, ConflictError, ValidationError
from logging_config import get_logger
from models.note import Note
from models.relationship import Relationship
from schemas.relationship import RelationshipCreate
from service.note_validation import ensure_active_notes_for_user

logger = get_logger(__name__)


def _peer_note_id(rel: Relationship, note_id: int) -> int:
    return rel.note_b_id if rel.note_a_id == note_id else rel.note_a_id


async def create_relationship(
    session: AsyncSession,
    data: RelationshipCreate,
    user_id: int,
) -> Relationship:
    if data.note_a_id == data.note_b_id:
        raise ValidationError("note_a_id and note_b_id must differ")
    await ensure_active_notes_for_user(
        session, [data.note_a_id, data.note_b_id], user_id
    )
    rel = Relationship(
        note_a_id=data.note_a_id,
        note_b_id=data.note_b_id,
        type=data.type,
    )
    session.add(rel)
    try:
        async with session.begin_nested():
            await session.flush()
            await session.refresh(rel)
    except IntegrityError:
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


async def filter_relationships_with_active_peers(
    session: AsyncSession,
    note_id: int,
    user_id: int,
    relationships: List[Relationship],
) -> List[Relationship]:
    """Keep only relationships whose peer note is active and owned by user_id."""
    other_note_ids = {_peer_note_id(rel, note_id) for rel in relationships}
    if not other_note_ids:
        return []
    result = await session.execute(
        select(Note.id).where(
            Note.id.in_(other_note_ids),
            Note.user_id == user_id,
            Note.is_deleted == False,
        )
    )
    active_peer_ids = {row[0] for row in result.all()}
    return [
        rel
        for rel in relationships
        if _peer_note_id(rel, note_id) in active_peer_ids
    ]


async def soft_delete_relationships_for_note(
    session: AsyncSession,
    note_id: int,
) -> int:
    """Soft-delete all active relationships involving note_id. Returns count updated."""
    result = await session.execute(
        select(Relationship).where(
            or_(
                Relationship.note_a_id == note_id,
                Relationship.note_b_id == note_id,
            ),
            Relationship.is_deleted == False,
        )
    )
    rels = list(result.scalars().all())
    for rel in rels:
        rel.is_deleted = True
        rel.version += 1
    if rels:
        await session.flush()
    return len(rels)


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


async def delete_relationship_for_user(
    session: AsyncSession,
    note_a_id: int,
    note_b_id: int,
    user_id: int,
) -> None:
    """Soft-delete a relationship if the user owns at least one endpoint note (incl. deleted)."""
    result = await session.execute(
        select(Relationship).where(
            Relationship.note_a_id == note_a_id,
            Relationship.note_b_id == note_b_id,
        )
    )
    rel = result.scalar_one_or_none()
    if not rel:
        raise NotFoundError("Relationship not found")

    notes_result = await session.execute(
        select(Note).where(Note.id.in_([note_a_id, note_b_id]))
    )
    notes = {n.id: n for n in notes_result.scalars().all()}
    note_a = notes.get(note_a_id)
    note_b = notes.get(note_b_id)
    owns_a = note_a is not None and note_a.user_id == user_id
    owns_b = note_b is not None and note_b.user_id == user_id
    if not owns_a and not owns_b:
        raise AuthorizationError("Not authorized to delete this relationship")

    await delete_relationship(session, note_a_id, note_b_id)


async def repair_stale_relationships(session: AsyncSession) -> int:
    """Soft-delete relationships whose endpoint note is soft-deleted. Returns count repaired."""
    result = await session.execute(
        select(Relationship)
        .join(Note, Note.id == Relationship.note_a_id)
        .where(
            Relationship.is_deleted == False,
            Note.is_deleted == True,
        )
    )
    stale_a = list(result.scalars().all())

    result = await session.execute(
        select(Relationship)
        .join(Note, Note.id == Relationship.note_b_id)
        .where(
            Relationship.is_deleted == False,
            Note.is_deleted == True,
        )
    )
    stale_b = list(result.scalars().all())

    seen: set[tuple[int, int]] = set()
    count = 0
    for rel in stale_a + stale_b:
        key = (rel.note_a_id, rel.note_b_id)
        if key in seen:
            continue
        seen.add(key)
        rel.is_deleted = True
        rel.version += 1
        count += 1
    if count:
        await session.flush()
        logger.info("Repaired %s stale relationship(s)", count)
    return count
