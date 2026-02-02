"""Purge soft-deleted rows older than a configured retention window."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from logging_config import get_logger
from models.category import Category
from models.chunk import Chunk
from models.note import Note
from models.note_category import NoteCategory
from models.relationship import Relationship

logger = get_logger(__name__)


def _utc_cutoff(weeks: int) -> datetime:
    """Return naive UTC cutoff so comparison with DB updated_at works (naive or aware)."""
    return (datetime.now(timezone.utc) - timedelta(weeks=weeks)).replace(tzinfo=None)


async def purge_soft_deleted_older_than(
    session: AsyncSession,
    weeks: int | None = None,
) -> dict[str, int]:
    """Hard-delete rows where is_deleted is true and updated_at is older than `weeks`.

    Returns a dict of table name -> number of rows deleted for each of the five
    tables (notes, categories, relationships, chunks, note_categories).
    """
    if weeks is None:
        weeks = settings.PURGE_SOFT_DELETED_AFTER_WEEKS
    cutoff = _utc_cutoff(weeks)

    result_counts: dict[str, int] = {}

    for table_name, model in [
        ("notes", Note),
        ("categories", Category),
        ("relationships", Relationship),
        ("chunks", Chunk),
        ("note_categories", NoteCategory),
    ]:
        stmt = delete(model).where(
            model.is_deleted == True,  # noqa: E712
            model.updated_at < cutoff,
        )
        r = await session.execute(
            stmt,
            execution_options={"synchronize_session": False},
        )
        count = r.rowcount if r.rowcount is not None else 0
        result_counts[table_name] = count
        if count:
            logger.info(
                "Purged %s soft-deleted rows from %s (updated_at < %s)",
                count,
                table_name,
                cutoff.isoformat(),
            )

    await session.commit()
    return result_counts
