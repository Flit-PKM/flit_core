"""Feedback service: create, list, and delete feedback."""

from typing import Any, List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import NotFoundError
from logging_config import get_logger
from models.feedback import Feedback
from models.feedback_response import FeedbackResponse

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
    search: Optional[str] = None,
) -> List[Feedback]:
    """Return all feedback with optional pagination, newest first."""
    q = select(Feedback)
    if search and search.strip():
        term = f"%{search.strip().lower()}%"
        q = q.where(func.lower(Feedback.content).like(term))
    q = q.offset(skip).limit(limit).order_by(Feedback.created_at.desc())
    result = await db.execute(q)
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


async def list_feedback_responses(
    db: AsyncSession,
    feedback_id: int,
) -> List[FeedbackResponse]:
    fb = await get_feedback_by_id(db, feedback_id)
    if not fb:
        raise NotFoundError("Feedback not found")
    result = await db.execute(
        select(FeedbackResponse)
        .where(FeedbackResponse.feedback_id == feedback_id)
        .order_by(FeedbackResponse.created_at.asc())
    )
    return list(result.scalars().all())


async def create_feedback_response(
    db: AsyncSession,
    feedback_id: int,
    author_user_id: int,
    body: str,
) -> FeedbackResponse:
    fb = await get_feedback_by_id(db, feedback_id)
    if not fb:
        raise NotFoundError("Feedback not found")
    row = FeedbackResponse(
        feedback_id=feedback_id,
        author_user_id=author_user_id,
        body=body,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


async def delete_feedback(db: AsyncSession, feedback_id: int) -> None:
    """Delete feedback by ID. Raises NotFoundError if not found."""
    feedback = await get_feedback_by_id(db, feedback_id)
    if not feedback:
        logger.warning(f"Delete attempted for non-existent feedback: {feedback_id}")
        raise NotFoundError("Feedback not found")
    await db.delete(feedback)
    await db.flush()
    logger.info(f"Feedback deleted: {feedback_id}")
