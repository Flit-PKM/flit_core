from __future__ import annotations

from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import NotFoundError
from logging_config import get_logger
from models.chunk import Chunk
from schemas.chunk import ChunkCreate, ChunkUpdate
from service.encryption import (
    decrypt_chunk_summary,
    encrypt_chunk_summary,
    is_encryption_enabled_for_user,
)
from service.note import get_note_or_404

logger = get_logger(__name__)


async def create_chunk(session: AsyncSession, data: ChunkCreate) -> Chunk:
    note = await get_note_or_404(session, data.note_id)
    dump = data.model_dump()
    if await is_encryption_enabled_for_user(session, note.user_id):
        dump["summary"] = await encrypt_chunk_summary(
            session, note.user_id, dump["summary"]
        )
        dump["encryption_version"] = 1
    db_chunk = Chunk(**dump)
    session.add(db_chunk)
    await session.flush()
    await session.refresh(db_chunk)
    if await is_encryption_enabled_for_user(session, note.user_id):
        await decrypt_chunk_summary(session, db_chunk)
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
    chunk = result.scalar_one_or_none()
    if chunk:
        from models.note import Note
        note_result = await session.execute(select(Note).where(Note.id == chunk.note_id))
        note = note_result.scalar_one_or_none()
        if note and await is_encryption_enabled_for_user(session, note.user_id):
            await decrypt_chunk_summary(session, chunk)
    return chunk


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
    from models.note import Note
    result = await session.execute(
        select(Chunk)
        .where(Chunk.note_id == note_id, Chunk.is_deleted == False)
        .offset(skip)
        .limit(limit)
    )
    chunks = list(result.scalars().all())
    note_result = await session.execute(select(Note).where(Note.id == note_id))
    note = note_result.scalar_one_or_none()
    if note and await is_encryption_enabled_for_user(session, note.user_id):
        for chunk in chunks:
            await decrypt_chunk_summary(session, chunk)
    return chunks


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
    from models.note import Note
    note_result = await session.execute(select(Note).where(Note.id == chunk.note_id))
    note = note_result.scalar_one_or_none()
    payload = data.model_dump(exclude_unset=True)
    if note and await is_encryption_enabled_for_user(session, note.user_id) and "summary" in payload:
        payload["summary"] = await encrypt_chunk_summary(
            session, note.user_id, payload["summary"]
        )
        payload["encryption_version"] = 1
    for field, value in payload.items():
        setattr(chunk, field, value)
    await session.flush()
    await session.refresh(chunk)
    if note and await is_encryption_enabled_for_user(session, note.user_id):
        await decrypt_chunk_summary(session, chunk)
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
