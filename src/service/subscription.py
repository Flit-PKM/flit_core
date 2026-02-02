from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import ConflictError, NotFoundError
from logging_config import get_logger
from models.subscription import Subscription

logger = get_logger(__name__)


def _normalize_email(email: str) -> str:
    """Normalize email to lowercase and strip whitespace."""
    return email.lower().strip()


async def create_subscription(db: AsyncSession, email: str) -> Subscription:
    """Add an email to the subscription list. Raises ConflictError if already subscribed."""
    normalized = _normalize_email(email)
    existing = await get_subscription_by_email(db, normalized)
    if existing:
        logger.warning(f"Subscription already exists for email: {normalized}")
        raise ConflictError("Email already subscribed")
    subscription = Subscription(email=normalized)
    db.add(subscription)
    await db.flush()
    await db.refresh(subscription)
    logger.info(f"Subscription created: {subscription.id} - {normalized}")
    return subscription


async def get_all_subscriptions(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 100,
) -> List[Subscription]:
    """Return all subscriptions with optional pagination."""
    result = await db.execute(
        select(Subscription).offset(skip).limit(limit).order_by(Subscription.created_at.desc())
    )
    return list(result.scalars().all())


async def get_subscription_by_email(
    db: AsyncSession,
    email: str,
) -> Optional[Subscription]:
    """Return subscription by email (case-insensitive), or None if not found."""
    normalized = _normalize_email(email)
    result = await db.execute(
        select(Subscription).where(func.lower(Subscription.email) == normalized)
    )
    return result.scalar_one_or_none()


async def delete_subscription_by_email(db: AsyncSession, email: str) -> None:
    """Remove an email from the subscription list. Raises NotFoundError if not on list."""
    subscription = await get_subscription_by_email(db, email)
    if not subscription:
        logger.warning(f"Delete attempted for email not on list: {email}")
        raise NotFoundError("Email not on list")
    await db.delete(subscription)
    await db.flush()
    logger.info(f"Subscription removed: {subscription.email}")
