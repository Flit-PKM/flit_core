"""REST endpoints to add or remove categories from notes (ownership-checked)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from auth.dependencies import get_current_active_user
from database.session import get_async_session
from logging_config import get_logger
from models.user import User
from schemas.note_category import NoteCategoryCreate, NoteCategoryRead
from service.category import get_category_or_404
from service.note import get_note
from service.note_category import link_note_category, unlink_note_category

logger = get_logger(__name__)

router = APIRouter(
    prefix="/note-categories",
    tags=["note-categories"],
)


@router.post("", response_model=NoteCategoryRead, status_code=status.HTTP_201_CREATED)
async def add_category_to_note(
    data: NoteCategoryCreate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Add a category to a note. Note and category must belong to the current user."""
    note = await get_note(db, data.note_id)
    if not note:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Note not found",
        )
    if note.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to modify this note",
        )
    await get_category_or_404(db, data.category_id, current_user.id)
    link = await link_note_category(db, data)
    await db.commit()
    await db.refresh(link)
    logger.info(
        f"User {current_user.id} added category {data.category_id} to note {data.note_id}"
    )
    return link


@router.delete("/{note_id}/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_category_from_note(
    note_id: int,
    category_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Remove a category from a note. Note and category must belong to the current user."""
    note = await get_note(db, note_id)
    if not note:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Note not found",
        )
    if note.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to modify this note",
        )
    await get_category_or_404(db, category_id, current_user.id)
    await unlink_note_category(db, note_id, category_id)
    await db.commit()
    logger.info(
        f"User {current_user.id} removed category {category_id} from note {note_id}"
    )
    return None
