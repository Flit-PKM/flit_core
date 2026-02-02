from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from auth.dependencies import OAuthContext, get_sync_oauth_context
from database.session import get_async_session
from logging_config import get_logger
from schemas.sync import (
    CategoriesCompareResult,
    CategorySync,
    ChunksCompareResult,
    ChunkSync,
    CompareCategoriesRequest,
    CompareChunksRequest,
    CompareNoteCategoriesRequest,
    CompareNotesRequest,
    CompareRelationshipsRequest,
    NoteCategoriesCompareResult,
    NoteCategorySync,
    NotesCompareResult,
    NoteSync,
    RelationshipsCompareResult,
    RelationshipSync,
    SyncCategoriesResponse,
    SyncCategoryPushResult,
    SyncChunkPushResult,
    SyncChunksResponse,
    SyncNoteCategoriesResponse,
    SyncNoteCategoryPushResult,
    SyncNoteCategoryRead,
    SyncNoteRead,
    SyncNotesResponse,
    SyncPushResult,
    SyncRelationshipPushResult,
    SyncRelationshipRead,
    SyncRelationshipsResponse,
    SyncCategoryRead,
    SyncChunkRead,
)
from service.sync import (
    compare_categories,
    compare_chunks,
    compare_note_categories,
    compare_notes,
    compare_relationships,
    get_categories_by_ids,
    get_chunks_by_ids,
    get_notes_by_ids,
    get_note_categories_by_keys,
    get_relationships_by_keys,
    sync_categories,
    sync_chunks,
    sync_note_categories,
    sync_notes,
    sync_relationships,
)

logger = get_logger(__name__)

router = APIRouter(
    prefix="/sync",
    tags=["sync"],
)


# ----- Per-table compare (POST /sync/compare/{table}) -----


@router.post("/compare/notes", response_model=NotesCompareResult)
async def compare_notes_route(
    body: CompareNotesRequest,
    oauth_ctx: OAuthContext = Depends(get_sync_oauth_context),
    db: AsyncSession = Depends(get_async_session),
):
    """Compare note versions between app and server. Returns to_pull (app should GET) and to_push (app should POST)."""
    user_id, connected_app_id = oauth_ctx.user_id, oauth_ctx.connected_app_id
    result = await compare_notes(db, user_id, connected_app_id, body.notes)
    print('\n')
    print('*'*100)
    print('\n')
    print('Comparing Notes:')
    print(body.notes)
    print('*'*100)
    print('\n')
    print('Comparing Notes Result:')
    print(result.model_dump_json(indent=2))
    print('*'*100)
    print('\n')
    return result


@router.post("/compare/categories", response_model=CategoriesCompareResult)
async def compare_categories_route(
    body: CompareCategoriesRequest,
    oauth_ctx: OAuthContext = Depends(get_sync_oauth_context),
    db: AsyncSession = Depends(get_async_session),
):
    """Compare category versions between app and server. Returns to_pull and to_push."""
    user_id, _ = oauth_ctx
    return await compare_categories(db, user_id, body.categories)


@router.post("/compare/relationships", response_model=RelationshipsCompareResult)
async def compare_relationships_route(
    body: CompareRelationshipsRequest,
    oauth_ctx: OAuthContext = Depends(get_sync_oauth_context),
    db: AsyncSession = Depends(get_async_session),
):
    """Compare relationship versions between app and server. Returns to_pull and to_push."""
    user_id, _ = oauth_ctx
    return await compare_relationships(db, user_id, body.relationships)


@router.post("/compare/chunks", response_model=ChunksCompareResult)
async def compare_chunks_route(
    body: CompareChunksRequest,
    oauth_ctx: OAuthContext = Depends(get_sync_oauth_context),
    db: AsyncSession = Depends(get_async_session),
):
    """Compare chunk versions between app and server. Returns to_pull and to_push."""
    user_id, _ = oauth_ctx
    return await compare_chunks(db, user_id, body.chunks)


@router.post("/compare/note-categories", response_model=NoteCategoriesCompareResult)
async def compare_note_categories_route(
    body: CompareNoteCategoriesRequest,
    oauth_ctx: OAuthContext = Depends(get_sync_oauth_context),
    db: AsyncSession = Depends(get_async_session),
):
    """Compare note_category versions between app and server. Returns to_pull and to_push."""
    user_id, _ = oauth_ctx
    return await compare_note_categories(db, user_id, body.note_categories)


# ----- Notes: GET fetch, POST push -----


@router.get("/notes", response_model=SyncNotesResponse)
async def get_notes(
    core_id: int = Query(..., description="Note core_id (server id, Note.id value)"),
    oauth_ctx: OAuthContext = Depends(get_sync_oauth_context),
    db: AsyncSession = Depends(get_async_session),
):
    """Get a single note by core_id (server id). Pull uses only core_id."""
    user_id, _ = oauth_ctx

    notes = await get_notes_by_ids(db, user_id, [core_id])
    if not notes:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Note with core_id={core_id} not found",
        )
    note = notes[0]
    return SyncNotesResponse(
        note=SyncNoteRead.model_validate(note).model_dump(by_alias=True)
    )


@router.post("/notes", response_model=SyncPushResult)
async def push_notes(
    note: NoteSync,
    oauth_ctx: OAuthContext = Depends(get_sync_oauth_context),
    db: AsyncSession = Depends(get_async_session),
):
    """Push a single note: create (core_id=None) or update (core_id set) with version conflict resolution. Request body is DB-only (no app_id)."""
    user_id, connected_app_id = oauth_ctx.user_id, oauth_ctx.connected_app_id
    results = await sync_notes(db, user_id, connected_app_id, [note])
    return results[0]


@router.get("/categories", response_model=SyncCategoriesResponse)
async def get_categories(
    core_id: int = Query(
        ...,
        description="Category core_id (server id, Category.id value)",
    ),
    oauth_ctx: OAuthContext = Depends(get_sync_oauth_context),
    db: AsyncSession = Depends(get_async_session),
):
    """Get a single category by core_id (server id). Pull uses only core_id."""
    user_id, _ = oauth_ctx
    categories = await get_categories_by_ids(db, user_id, [core_id])
    if not categories:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Category with core_id={core_id} not found",
        )
    category = categories[0]
    return SyncCategoriesResponse(
        category=SyncCategoryRead.model_validate(category).model_dump(by_alias=True)
    )


@router.post("/categories", response_model=SyncCategoryPushResult)
async def push_categories(
    category: CategorySync,
    oauth_ctx: OAuthContext = Depends(get_sync_oauth_context),
    db: AsyncSession = Depends(get_async_session),
):
    """Push a single category: create or update with version conflict resolution."""
    user_id, _ = oauth_ctx
    results = await sync_categories(db, user_id, [category])
    return results[0]


@router.get("/chunks", response_model=SyncChunksResponse)
async def get_chunks(
    core_id: int = Query(
        ...,
        description="Chunk core_id (server id, Chunk.id value)",
    ),
    oauth_ctx: OAuthContext = Depends(get_sync_oauth_context),
    db: AsyncSession = Depends(get_async_session),
):
    """Get a single chunk by core_id (server id). Pull uses only core_id. Only chunks whose note belongs to the user."""
    user_id, _ = oauth_ctx
    chunks = await get_chunks_by_ids(db, user_id, [core_id])
    if not chunks:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Chunk with core_id={core_id} not found",
        )
    chunk = chunks[0]
    return SyncChunksResponse(
        chunk=SyncChunkRead.model_validate(chunk).model_dump(by_alias=True)
    )


@router.post("/chunks", response_model=SyncChunkPushResult)
async def push_chunks(
    chunk: ChunkSync,
    oauth_ctx: OAuthContext = Depends(get_sync_oauth_context),
    db: AsyncSession = Depends(get_async_session),
):
    """Push a single chunk: create or update with version conflict resolution."""
    user_id, _ = oauth_ctx
    results = await sync_chunks(db, user_id, [chunk])
    return results[0]


@router.get("/relationships", response_model=SyncRelationshipsResponse)
async def get_relationship(
    note_a_core_id: int = Query(
        ...,
        description="First note core_id (server id)",
    ),
    note_b_core_id: int = Query(
        ...,
        description="Second note core_id (server id)",
    ),
    oauth_ctx: OAuthContext = Depends(get_sync_oauth_context),
    db: AsyncSession = Depends(get_async_session),
):
    """Get a single relationship by (note_a_core_id, note_b_core_id) keys."""
    user_id, _ = oauth_ctx
    keys = [(note_a_core_id, note_b_core_id)]
    relationships = await get_relationships_by_keys(db, user_id, keys)
    if not relationships:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Relationship with note_a_core_id={note_a_core_id}, "
                f"note_b_core_id={note_b_core_id} not found"
            ),
        )
    relationship = relationships[0]
    return SyncRelationshipsResponse(
        relationship=SyncRelationshipRead.model_validate(
            relationship
        ).model_dump(by_alias=True)
    )


@router.post("/relationships", response_model=SyncRelationshipPushResult)
async def push_relationships(
    relationship: RelationshipSync,
    oauth_ctx: OAuthContext = Depends(get_sync_oauth_context),
    db: AsyncSession = Depends(get_async_session),
):
    """Push a single relationship: create or update with version conflict resolution."""
    user_id, _ = oauth_ctx  
    results = await sync_relationships(db, user_id, [relationship])
    return results[0]


@router.get("/note-categories", response_model=SyncNoteCategoriesResponse)
async def get_note_category(
    note_core_id: int = Query(
        ...,
        description="Note core_id (server id)",
    ),
    category_core_id: int = Query(
        ...,
        description="Category core_id (server id)",
    ),
    oauth_ctx: OAuthContext = Depends(get_sync_oauth_context),
    db: AsyncSession = Depends(get_async_session),
):
    """Get a single note_category link by (note_core_id, category_core_id) keys."""
    user_id, _ = oauth_ctx
    keys = [(note_core_id, category_core_id)]
    note_categories = await get_note_categories_by_keys(db, user_id, keys)
    if not note_categories:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"NoteCategory with note_core_id={note_core_id}, "
                f"category_core_id={category_core_id} not found"
            ),
        )
    note_category = note_categories[0]
    return SyncNoteCategoriesResponse(
        note_category=SyncNoteCategoryRead.model_validate(
            note_category
        ).model_dump(by_alias=True)
    )


@router.post("/note-categories", response_model=SyncNoteCategoryPushResult)
async def push_note_category(
    note_category: NoteCategorySync,
    oauth_ctx: OAuthContext = Depends(get_sync_oauth_context),
    db: AsyncSession = Depends(get_async_session),
):
    """Push a single note-category link: create or update with version conflict resolution."""
    user_id, _ = oauth_ctx
    results = await sync_note_categories(db, user_id, [note_category])
    return results[0]
