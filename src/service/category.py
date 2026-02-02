from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import NotFoundError, ConflictError
from logging_config import get_logger
from models.category import Category
from schemas.category import CategoryCreate, CategoryUpdate

logger = get_logger(__name__)


async def create_category(
    session: AsyncSession, data: CategoryCreate, user_id: int
) -> Category:
    """Create a new category for a user."""
    category_dict = data.model_dump()
    category_dict["user_id"] = user_id
    db_category = Category(**category_dict)
    session.add(db_category)
    try:
        await session.flush()
        await session.refresh(db_category)
    except IntegrityError:
        await session.rollback()
        raise ConflictError("Category with this name already exists for this user") from None
    logger.info("Category created: id=%s, name=%s, user_id=%s", db_category.id, db_category.name, user_id)
    return db_category


async def get_category(
    session: AsyncSession, category_id: int, user_id: Optional[int] = None
) -> Category | None:
    """Get an active (non-deleted) category by ID, optionally filtering by user_id."""
    query = select(Category).where(
        Category.id == category_id,
        Category.is_deleted == False,
    )
    if user_id is not None:
        query = query.where(Category.user_id == user_id)
    result = await session.execute(query)
    return result.scalar_one_or_none()


async def get_category_or_404(
    session: AsyncSession, category_id: int, user_id: Optional[int] = None
) -> Category:
    """Get a category by ID or raise 404, optionally filtering by user_id for ownership verification."""
    category = await get_category(session, category_id, user_id)
    if not category:
        raise NotFoundError("Category not found")
    return category


async def get_all_categories(
    session: AsyncSession,
    user_id: int,
    *,
    skip: int = 0,
    limit: int = 100,
) -> List[Category]:
    """Get all active (non-deleted) categories for a specific user."""
    result = await session.execute(
        select(Category)
        .where(Category.user_id == user_id, Category.is_deleted == False)
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())


async def update_category(
    session: AsyncSession,
    category_id: int,
    data: CategoryUpdate,
    user_id: int,
) -> Category:
    """Update a category, verifying ownership first."""
    category = await get_category_or_404(session, category_id, user_id)
    payload = data.model_dump(exclude_unset=True)
    for field, value in payload.items():
        setattr(category, field, value)
    try:
        await session.flush()
        await session.refresh(category)
    except IntegrityError:
        await session.rollback()
        raise ConflictError("Category with this name already exists for this user") from None
    logger.info("Category updated: id=%s, user_id=%s", category_id, user_id)
    return category


async def delete_category(
    session: AsyncSession, category_id: int, user_id: int
) -> None:
    """Soft-delete a category by id and user_id. Idempotent if already soft-deleted."""
    result = await session.execute(
        select(Category).where(
            Category.id == category_id,
            Category.user_id == user_id,
        )
    )
    category = result.scalar_one_or_none()
    if not category:
        raise NotFoundError("Category not found")
    category.is_deleted = True
    category.version += 1
    await session.flush()
    logger.info("Category soft-deleted: id=%s, user_id=%s", category_id, user_id)
