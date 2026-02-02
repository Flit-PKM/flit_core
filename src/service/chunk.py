from __future__ import annotations

from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import NotFoundError
from logging_config import get_logger
from models.chunk import Chunk
from schemas.chunk import ChunkCreate, ChunkUpdate

logger = get_logger(__name__)


async def create_chunk(session: AsyncSession, data: ChunkCreate) -> Chunk:
    from service.note import get_note_or_404

    await get_note_or_404(session, data.note_id)
    db_chunk = Chunk(**data.model_dump())
    session.add(db_chunk)
    await session.flush()
    await session.refresh(db_chunk)
    logger.info("Chunk created: id=%s, note_id=%s", db_chunk.id, db_chunk.note_id)
    return db_chunk


async def get_chunk(session: AsyncSession, chunk_id: int) -> Chunk | None:
    """Get an active (non-deleted) chunk by id."""
    result = await session.execute(
        select(Chunk).where(
            Chunk.id == chunk_id,
            Chunk.is_deleted == False,
        )
    )
    return result.scalar_one_or_none()


async def get_chunk_or_404(session: AsyncSession, chunk_id: int) -> Chunk:
    chunk = await get_chunk(session, chunk_id)
    if not chunk:
        raise NotFoundError("Chunk not found")
    return chunk


async def get_chunks_by_note(
    session: AsyncSession,
    note_id: int,
    *,
    skip: int = 0,
    limit: int = 500,
) -> List[Chunk]:
    """List active (non-deleted) chunks for a note."""
    result = await session.execute(
        select(Chunk)
        .where(Chunk.note_id == note_id, Chunk.is_deleted == False)
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_all_chunks(
    session: AsyncSession,
    *,
    skip: int = 0,
    limit: int = 100,
) -> List[Chunk]:
    """List active (non-deleted) chunks."""
    result = await session.execute(
        select(Chunk)
        .where(Chunk.is_deleted == False)
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())


async def update_chunk(
    session: AsyncSession,
    chunk_id: int,
    data: ChunkUpdate,
) -> Chunk:
    chunk = await get_chunk_or_404(session, chunk_id)
    payload = data.model_dump(exclude_unset=True)
    for field, value in payload.items():
        setattr(chunk, field, value)
    await session.flush()
    await session.refresh(chunk)
    logger.info("Chunk updated: id=%s", chunk_id)
    return chunk


async def delete_chunk(session: AsyncSession, chunk_id: int) -> None:
    """Soft-delete a chunk by id. Idempotent if already soft-deleted."""
    result = await session.execute(select(Chunk).where(Chunk.id == chunk_id))
    chunk = result.scalar_one_or_none()
    if not chunk:
        raise NotFoundError("Chunk not found")
    chunk.is_deleted = True
    chunk.version += 1
    await session.flush()
    logger.info("Chunk soft-deleted: id=%s", chunk_id)
