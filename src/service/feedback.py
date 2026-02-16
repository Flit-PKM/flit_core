"""Feedback service: create, list, and delete feedback."""

from typing import Any, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import NotFoundError
from logging_config import get_logger
from models.feedback import Feedback

logger = get_logger(__name__)


async def create_feedback(
    db: AsyncSession,
    content: str,
    context: Optional[dict[str, Any]] = None,
) -> Feedback:
    """Create a new feedback entry."""
    feedback = Feedback(content=content, context=context)
    db.add(feedback)
    await db.flush()
    await db.refresh(feedback)
    logger.info(f"Feedback created: {feedback.id}")
    return feedback


async def list_feedbacks(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 100,
) -> List[Feedback]:
    """Return all feedback with optional pagination, newest first."""
    result = await db.execute(
        select(Feedback)
        .offset(skip)
        .limit(limit)
        .order_by(Feedback.created_at.desc())
    )
    return list(result.scalars().all())


async def get_feedback_by_id(
    db: AsyncSession,
    feedback_id: int,
) -> Optional[Feedback]:
    """Return feedback by ID, or None if not found."""
    result = await db.execute(
        select(Feedback).where(Feedback.id == feedback_id)
    )
    return result.scalar_one_or_none()


async def delete_feedback(db: AsyncSession, feedback_id: int) -> None:
    """Delete feedback by ID. Raises NotFoundError if not found."""
    feedback = await get_feedback_by_id(db, feedback_id)
    if not feedback:
        logger.warning(f"Delete attempted for non-existent feedback: {feedback_id}")
        raise NotFoundError("Feedback not found")
    await db.delete(feedback)
    await db.flush()
    logger.info(f"Feedback deleted: {feedback_id}")
