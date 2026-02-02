from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from auth.dependencies import get_current_active_user
from database.session import get_async_session
from logging_config import get_logger
from models.user import User
from schemas.relationship import RelationshipCreate, RelationshipRead
from service.note import get_note
from service.relationship import (
    create_relationship,
    delete_relationship,
    get_relationship_or_404,
    list_relationships_for_note,
)

logger = get_logger(__name__)

router = APIRouter(
    prefix="/relationships",
    tags=["relationships"],
)


async def _verify_note_ownership(
    db: AsyncSession,
    note_id: int,
    user_id: int,
) -> None:
    """Verify that a note belongs to the user."""
    note = await get_note(db, note_id)
    if not note:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Note not found: id={note_id}",
        )
    if note.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Not authorized to access note: id={note_id}",
        )


@router.get("", response_model=List[RelationshipRead])
async def list_relationships(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
    note_id: Optional[int] = Query(None, description="Filter relationships for a specific note"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
):
    """List relationships. If note_id is provided, list relationships for that note (verifies ownership)."""
    if note_id is not None:
        # Verify note ownership
        await _verify_note_ownership(db, note_id, current_user.id)
        relationships = await list_relationships_for_note(
            db, note_id, skip=skip, limit=limit
        )
        # Filter to only return relationships where both notes belong to the user
        filtered_rels = []
        for rel in relationships:
            # Check both notes belong to user
            note_a = await get_note(db, rel.note_a_id)
            note_b = await get_note(db, rel.note_b_id)
            if note_a and note_b and note_a.user_id == current_user.id and note_b.user_id == current_user.id:
                filtered_rels.append(rel)
        logger.info(
            f"User {current_user.id} fetched {len(filtered_rels)} relationships for note {note_id}"
        )
        return filtered_rels
    else:
        # Without note_id, we'd need to list all relationships for the user
        # This is more complex, so for now we require note_id
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="note_id query parameter is required",
        )


@router.get("/{note_a_id}/{note_b_id}", response_model=RelationshipRead)
async def get_relationship_by_ids(
    note_a_id: int,
    note_b_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Get a specific relationship by note IDs. Verifies both notes belong to the user."""
    # Verify both notes belong to user
    await _verify_note_ownership(db, note_a_id, current_user.id)
    await _verify_note_ownership(db, note_b_id, current_user.id)
    
    relationship = await get_relationship_or_404(db, note_a_id, note_b_id)
    logger.info(
        f"User {current_user.id} fetched relationship: {note_a_id} -> {note_b_id}"
    )
    return relationship


@router.post("", response_model=RelationshipRead, status_code=status.HTTP_201_CREATED)
async def create_relationship_endpoint(
    relationship_data: RelationshipCreate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Create a new relationship. Verifies both notes belong to the user."""
    # Verify both notes belong to user
    await _verify_note_ownership(db, relationship_data.note_a_id, current_user.id)
    await _verify_note_ownership(db, relationship_data.note_b_id, current_user.id)
    
    relationship = await create_relationship(db, relationship_data)
    logger.info(
        f"User {current_user.id} created relationship: {relationship_data.note_a_id} -> {relationship_data.note_b_id}"
    )
    return relationship


@router.delete("/{note_a_id}/{note_b_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_relationship_endpoint(
    note_a_id: int,
    note_b_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Delete a relationship. Verifies both notes belong to the user."""
    # Verify both notes belong to user
    await _verify_note_ownership(db, note_a_id, current_user.id)
    await _verify_note_ownership(db, note_b_id, current_user.id)
    
    await delete_relationship(db, note_a_id, note_b_id)
    logger.info(
        f"User {current_user.id} deleted relationship: {note_a_id} -> {note_b_id}"
    )
    return None
