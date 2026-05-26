"""MCP tools for Flit PKM — registered on flit_mcp_router."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from flit_mcp.auth.context import McpAuthContext
from flit_mcp.auth.contextvar import get_current_mcp_auth
from flit_mcp.auth.dependencies import require_mcp_write
from flit_mcp.db import mcp_db_session
from flit_mcp.router_setup import flit_mcp_router
from flit_mcp.serialize import dump_model, dump_models
from models.note import Note, NoteType
from models.relationship import RelationshipType
from schemas.category import CategoryCreate, CategoryRead, CategoryUpdate
from schemas.note import NoteCreate, NoteCreateRequest, NoteDetailRead, NoteRead, NoteUpdate
from schemas.note_category import NoteCategoryCreate, NoteCategoryRead
from schemas.relationship import RelationshipCreate, RelationshipRead
from service.access_code import get_active_access_grant
from service.billing import SUBSCRIPTION_STATUS_ACTIVE, get_subscription_for_user
from service.category import (
    create_category as create_category_svc,
    delete_category as delete_category_svc,
    get_all_categories,
    get_category_or_404,
    update_category as update_category_svc,
)
from service.note import (
    create_note as create_note_svc,
    delete_note as delete_note_svc,
    get_note as get_note_svc,
    get_notes_by_user,
    update_note as update_note_svc,
)
from service.note_category import (
    link_note_category,
    list_categories_for_note,
    unlink_note_category,
)
from service.relationship import (
    create_relationship as create_relationship_svc,
    delete_relationship as delete_relationship_svc,
    list_relationships_for_note,
)
from service.user import get_user
from sqlalchemy.ext.asyncio import AsyncSession


def _write_guard(ctx: McpAuthContext) -> None:
    require_mcp_write(ctx)


async def _build_note_detail_read(
    db: AsyncSession,
    note_id: int,
    user_id: int,
    note: Note,
) -> NoteDetailRead:
    """Match REST GET /notes/{id} — categories and owned peer relationships."""
    categories_raw = await list_categories_for_note(db, note_id)
    categories = [
        CategoryRead.model_validate(c)
        for c in categories_raw
        if c.user_id == user_id
    ]

    relationships_raw = await list_relationships_for_note(
        db, note_id, skip=0, limit=1000
    )
    other_note_ids = {
        rel.note_b_id if rel.note_a_id == note_id else rel.note_a_id
        for rel in relationships_raw
    }
    if other_note_ids:
        result = await db.execute(
            select(Note.id).where(
                Note.id.in_(other_note_ids),
                Note.user_id == user_id,
            )
        )
        user_other_note_ids = {row[0] for row in result.all()}
    else:
        user_other_note_ids = set()

    filtered_rels = [
        rel
        for rel in relationships_raw
        if (rel.note_b_id if rel.note_a_id == note_id else rel.note_a_id)
        in user_other_note_ids
    ]
    relationships = [RelationshipRead.model_validate(r) for r in filtered_rels]

    return NoteDetailRead(
        **NoteRead.model_validate(note).model_dump(),
        categories=categories,
        relationships=relationships,
    )


@flit_mcp_router.tool()
async def list_notes(
    skip: int = 0,
    limit: int = 100,
    category_name: str | None = None,
    search: str | None = None,
) -> list[dict[str, Any]]:
    """List the authenticated user's notes with optional category filter and full-text search.

    Use for discovery before get_note. Requires read scope. limit max 1000.
    """
    ctx = get_current_mcp_auth()
    limit = min(max(limit, 1), 1000)
    async with mcp_db_session() as db:
        notes = await get_notes_by_user(
            db,
            ctx.user_id,
            skip=skip,
            limit=limit,
            category_name=category_name.strip() if category_name else None,
            search=search.strip() if search else None,
        )
        return dump_models([NoteRead.model_validate(n) for n in notes])


@flit_mcp_router.tool()
async def get_note(note_id: int) -> dict[str, Any]:
    """Get one note by id including title, content, categories, and relationships.

    Requires read scope. Only your notes.
    """
    ctx = get_current_mcp_auth()
    async with mcp_db_session() as db:
        note = await get_note_svc(db, note_id)
        if not note or note.user_id != ctx.user_id:
            from exceptions import NotFoundError

            raise NotFoundError("Note not found")
        detail = await _build_note_detail_read(db, note_id, ctx.user_id, note)
        return dump_model(detail)


@flit_mcp_router.tool()
async def create_note(
    title: str,
    content: str,
    type: str = "BASE",
    pinned: bool = False,
    color: str = "",
) -> dict[str, Any]:
    """Create a new note. Requires read write scope."""
    ctx = get_current_mcp_auth()
    _write_guard(ctx)
    note_type = NoteType(type) if type in NoteType.__members__ else NoteType.BASE
    body = NoteCreateRequest(
        title=title,
        content=content,
        type=note_type,
        pinned=pinned,
        color=color,
    )
    async with mcp_db_session() as db:
        note_create = NoteCreate(**body.model_dump(), user_id=ctx.user_id)
        note = await create_note_svc(db, note_create)
        return dump_model(NoteRead.model_validate(note))


@flit_mcp_router.tool()
async def update_note(
    note_id: int,
    title: str | None = None,
    content: str | None = None,
    pinned: bool | None = None,
    color: str | None = None,
) -> dict[str, Any]:
    """Update an existing note. Requires read write scope. Only your notes."""
    ctx = get_current_mcp_auth()
    _write_guard(ctx)
    async with mcp_db_session() as db:
        note = await get_note_svc(db, note_id)
        if not note or note.user_id != ctx.user_id:
            from exceptions import NotFoundError

            raise NotFoundError("Note not found")
        payload: dict[str, Any] = {}
        if title is not None:
            payload["title"] = title
        if content is not None:
            payload["content"] = content
        if pinned is not None:
            payload["pinned"] = pinned
        if color is not None:
            payload["color"] = color
        updated = await update_note_svc(db, note_id, NoteUpdate(**payload))
        return dump_model(NoteRead.model_validate(updated))


@flit_mcp_router.tool()
async def delete_note(note_id: int) -> dict[str, bool]:
    """Soft-delete a note. Requires read write scope."""
    ctx = get_current_mcp_auth()
    _write_guard(ctx)
    async with mcp_db_session() as db:
        await delete_note_svc(db, note_id, ctx.user_id)
        return {"deleted": True}


@flit_mcp_router.tool()
async def list_categories(
    skip: int = 0,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """List categories for the authenticated user. Requires read scope."""
    ctx = get_current_mcp_auth()
    limit = min(max(limit, 1), 1000)
    async with mcp_db_session() as db:
        cats = await get_all_categories(db, ctx.user_id, skip=skip, limit=limit)
        return dump_models([CategoryRead.model_validate(c) for c in cats])


@flit_mcp_router.tool()
async def get_category(category_id: int) -> dict[str, Any]:
    """Get a category by id. Requires read scope."""
    ctx = get_current_mcp_auth()
    async with mcp_db_session() as db:
        cat = await get_category_or_404(db, category_id, ctx.user_id)
        return dump_model(CategoryRead.model_validate(cat))


@flit_mcp_router.tool()
async def create_category(name: str) -> dict[str, Any]:
    """Create a category. Requires read write scope."""
    ctx = get_current_mcp_auth()
    _write_guard(ctx)
    async with mcp_db_session() as db:
        cat = await create_category_svc(db, CategoryCreate(name=name), ctx.user_id)
        return dump_model(CategoryRead.model_validate(cat))


@flit_mcp_router.tool()
async def update_category(category_id: int, name: str) -> dict[str, Any]:
    """Rename a category. Requires read write scope."""
    ctx = get_current_mcp_auth()
    _write_guard(ctx)
    async with mcp_db_session() as db:
        cat = await update_category_svc(
            db, category_id, CategoryUpdate(name=name), ctx.user_id
        )
        return dump_model(CategoryRead.model_validate(cat))


@flit_mcp_router.tool()
async def delete_category(category_id: int) -> dict[str, bool]:
    """Delete a category. Requires read write scope."""
    ctx = get_current_mcp_auth()
    _write_guard(ctx)
    async with mcp_db_session() as db:
        await delete_category_svc(db, category_id, ctx.user_id)
        return {"deleted": True}


@flit_mcp_router.tool()
async def list_relationships(
    note_id: int,
    skip: int = 0,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """List relationships for a note. Requires read scope. note_id is required."""
    ctx = get_current_mcp_auth()
    async with mcp_db_session() as db:
        note = await get_note_svc(db, note_id)
        if not note or note.user_id != ctx.user_id:
            from exceptions import NotFoundError

            raise NotFoundError("Note not found")
        rels = await list_relationships_for_note(db, note_id, skip=skip, limit=limit)
        return dump_models([RelationshipRead.model_validate(r) for r in rels])


@flit_mcp_router.tool()
async def create_relationship(
    note_a_id: int,
    note_b_id: int,
    type: str = "RELATED_TO",
) -> dict[str, Any]:
    """Create a relationship between two notes. Requires read write scope."""
    ctx = get_current_mcp_auth()
    _write_guard(ctx)
    async with mcp_db_session() as db:
        for nid in (note_a_id, note_b_id):
            n = await get_note_svc(db, nid)
            if not n or n.user_id != ctx.user_id:
                from exceptions import NotFoundError

                raise NotFoundError(f"Note not found: {nid}")
        rel_type = (
            RelationshipType(type)
            if type in RelationshipType.__members__
            else RelationshipType.RELATED_TO
        )
        rel = await create_relationship_svc(
            db,
            RelationshipCreate(
                note_a_id=note_a_id,
                note_b_id=note_b_id,
                type=rel_type,
            ),
        )
        return dump_model(RelationshipRead.model_validate(rel))


@flit_mcp_router.tool()
async def delete_relationship(note_a_id: int, note_b_id: int) -> dict[str, bool]:
    """Delete a relationship between two notes. Requires read write scope."""
    ctx = get_current_mcp_auth()
    _write_guard(ctx)
    async with mcp_db_session() as db:
        for nid in (note_a_id, note_b_id):
            n = await get_note_svc(db, nid)
            if not n or n.user_id != ctx.user_id:
                from exceptions import NotFoundError

                raise NotFoundError(f"Note not found: {nid}")
        await delete_relationship_svc(db, note_a_id, note_b_id)
        return {"deleted": True}


@flit_mcp_router.tool()
async def list_note_categories(note_id: int) -> list[dict[str, Any]]:
    """List categories linked to a note. Requires read scope."""
    ctx = get_current_mcp_auth()
    async with mcp_db_session() as db:
        note = await get_note_svc(db, note_id)
        if not note or note.user_id != ctx.user_id:
            from exceptions import NotFoundError

            raise NotFoundError("Note not found")
        cats = await list_categories_for_note(db, note_id)
        owned = [c for c in cats if c.user_id == ctx.user_id]
        return dump_models([CategoryRead.model_validate(c) for c in owned])


@flit_mcp_router.tool()
async def link_note_to_category(note_id: int, category_id: int) -> dict[str, Any]:
    """Link a note to a category. Requires read write scope."""
    ctx = get_current_mcp_auth()
    _write_guard(ctx)
    async with mcp_db_session() as db:
        note = await get_note_svc(db, note_id)
        if not note or note.user_id != ctx.user_id:
            from exceptions import NotFoundError

            raise NotFoundError("Note not found")
        await get_category_or_404(db, category_id, ctx.user_id)
        link = await link_note_category(
            db, NoteCategoryCreate(note_id=note_id, category_id=category_id)
        )
        return dump_model(NoteCategoryRead.model_validate(link))


@flit_mcp_router.tool()
async def unlink_note_from_category(note_id: int, category_id: int) -> dict[str, bool]:
    """Remove a note–category link. Requires read write scope."""
    ctx = get_current_mcp_auth()
    _write_guard(ctx)
    async with mcp_db_session() as db:
        note = await get_note_svc(db, note_id)
        if not note or note.user_id != ctx.user_id:
            from exceptions import NotFoundError

            raise NotFoundError("Note not found")
        await get_category_or_404(db, category_id, ctx.user_id)
        await unlink_note_category(db, note_id, category_id)
        return {"deleted": True}


@flit_mcp_router.tool()
async def get_user_profile() -> dict[str, Any]:
    """Get the authenticated user's profile and subscription summary. Read scope only."""
    ctx = get_current_mcp_auth()
    async with mcp_db_session() as db:
        user = await get_user(db, ctx.user_id)
        if not user:
            from exceptions import NotFoundError

            raise NotFoundError("User not found")
        sub = await get_subscription_for_user(db, ctx.user_id)
        grant = await get_active_access_grant(db, ctx.user_id)
        entitlement_active = bool(
            grant or (sub and sub.status == SUBSCRIPTION_STATUS_ACTIVE)
        )
        return {
            "id": user.id,
            "email": user.email,
            "username": user.username,
            "is_active": user.is_active,
            "is_verified": user.is_verified,
            "entitlement_active": entitlement_active,
        }
