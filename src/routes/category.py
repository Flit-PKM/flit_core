from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from auth.dependencies import get_current_active_user
from database.session import get_async_session
from logging_config import get_logger
from models.user import User
from schemas.category import CategoryCreate, CategoryRead, CategoryUpdate
from service.category import (
    create_category,
    delete_category,
    get_all_categories,
    get_category_or_404,
    update_category,
)

logger = get_logger(__name__)

router = APIRouter(
    prefix="/categories",
    tags=["categories"],
)


@router.get("", response_model=List[CategoryRead])
async def list_categories(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
):
    """List all categories for the authenticated user."""
    categories = await get_all_categories(db, current_user.id, skip=skip, limit=limit)
    logger.info(f"User {current_user.id} fetched {len(categories)} categories")
    return categories


@router.get("/{category_id}", response_model=CategoryRead)
async def get_category_by_id(
    category_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Get a specific category by ID. Verifies ownership."""
    category = await get_category_or_404(db, category_id, current_user.id)
    logger.info(f"User {current_user.id} fetched category {category_id}")
    return category


@router.post("", response_model=CategoryRead, status_code=status.HTTP_201_CREATED)
async def create_category_endpoint(
    category_data: CategoryCreate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Create a new category for the authenticated user."""
    category = await create_category(db, category_data, current_user.id)
    logger.info(f"User {current_user.id} created category {category.id}")
    return category


@router.put("/{category_id}", response_model=CategoryRead)
async def update_category_endpoint(
    category_id: int,
    category_data: CategoryUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Update a category. Verifies ownership."""
    updated_category = await update_category(db, category_id, category_data, current_user.id)
    logger.info(f"User {current_user.id} updated category {category_id}")
    return updated_category


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category_endpoint(
    category_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Delete a category. Verifies ownership."""
    await delete_category(db, category_id, current_user.id)
    logger.info(f"User {current_user.id} deleted category {category_id}")
    return None
