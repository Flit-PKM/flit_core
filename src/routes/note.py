from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.dependencies import get_current_active_user
from openapi_responses import owned_resource
from database.session import get_async_session
from exceptions import NotFoundError
from logging_config import get_logger
from models.connected_app import ConnectedApp
from models.user import User
from schemas.category import CategoryRead
from schemas.note import NoteCreate, NoteCreateRequest, NoteDetailRead, NoteRead, NoteUpdate
from schemas.relationship import RelationshipRead
from service.note import (
    create_note,
    delete_note,
    get_note,
    get_notes_by_user,
    update_note,
)
from service.note_category import list_categories_for_note
from service.relationship import (
    filter_relationships_with_active_peers,
    list_relationships_for_note,
)

logger = get_logger(__name__)

router = APIRouter(
    prefix="/notes",
    tags=["notes"],
)


@router.get("", response_model=List[NoteRead])
async def list_notes(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
    skip: int = Query(0, ge=0, examples=[0]),
    limit: int = Query(100, ge=1, le=1000, examples=[20]),
    filter: str | None = Query(
        None, description="Filter by category name", examples=["work"]
    ),
    search: str | None = Query(
        None, description="Search in title and content", examples=["meeting"]
    ),
):
    """List all notes for the authenticated user."""
    category_name = filter.strip() if filter else None
    search_term = search.strip() if search else None
    notes = await get_notes_by_user(
        db,
        current_user.id,
        skip=skip,
        limit=limit,
        category_name=category_name,
        search=search_term,
    )
    logger.info(f"User {current_user.id} fetched {len(notes)} notes")
    return notes


@router.get(
    "/{note_id}",
    response_model=NoteDetailRead,
    responses=owned_resource(
        forbidden="Not authorized to access this note",
        not_found="Note not found",
    ),
)
async def get_note_by_id(
    note_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Get a specific note by ID with categories and relationships. Verifies ownership."""
    note = await get_note(db, note_id)

    if not note:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Note not found",
        )

    if note.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this note",
        )

    categories_raw = await list_categories_for_note(db, note_id)
    categories = [
        CategoryRead.model_validate(c)
        for c in categories_raw
        if c.user_id == current_user.id
    ]

    relationships_raw = await list_relationships_for_note(
        db, note_id, skip=0, limit=1000
    )
    filtered_rels = await filter_relationships_with_active_peers(
        db, note_id, current_user.id, relationships_raw
    )
    relationships = [RelationshipRead.model_validate(r) for r in filtered_rels]

    note_detail = NoteDetailRead(
        **NoteRead.model_validate(note).model_dump(),
        categories=categories,
        relationships=relationships,
    )
    logger.info(
        f"User {current_user.id} fetched note {note_id} "
        f"(categories={len(categories)}, relationships={len(relationships)})"
    )
    return note_detail


@router.post("", response_model=NoteRead, status_code=status.HTTP_201_CREATED)
async def create_note_endpoint(
    note_data: NoteCreateRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Create a new note for the authenticated user."""
    if note_data.source_id is not None:
        result = await db.execute(
            select(ConnectedApp).where(
                ConnectedApp.id == note_data.source_id,
                ConnectedApp.user_id == current_user.id,
            )
        )
        if not result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid source_id for this user",
            )

    note_create = NoteCreate(
        **note_data.model_dump(),
        user_id=current_user.id,
    )

    note = await create_note(db, note_create)
    logger.info(f"User {current_user.id} created note {note.id}")
    return note


@router.put(
    "/{note_id}",
    response_model=NoteRead,
    responses=owned_resource(
        forbidden="Not authorized to modify this note",
        not_found="Note not found",
    ),
)
async def update_note_endpoint(
    note_id: int,
    note_data: NoteUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Update a note. Verifies ownership."""
    # Verify ownership first
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
    
    updated_note = await update_note(db, note_id, note_data)
    logger.info(f"User {current_user.id} updated note {note_id}")
    return updated_note


@router.delete(
    "/{note_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=owned_resource(not_found="Note not found"),
)
async def delete_note_endpoint(
    note_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Soft-delete a note. Verifies ownership."""
    try:
        await delete_note(db, note_id, current_user.id)
    except NotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Note not found",
        )
    logger.info(f"User {current_user.id} deleted note {note_id}")
    return None
