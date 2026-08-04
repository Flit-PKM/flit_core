"""MCP tools for Flit PKM — registered on flit_mcp_router."""

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import NotFoundError, ValidationError
from flit_mcp.auth.context import McpAuthContext
from flit_mcp.auth.contextvar import get_current_mcp_auth
from flit_mcp.auth.dependencies import require_mcp_write
from flit_mcp.db import mcp_db_session
from flit_mcp.errors import note_not_found
from flit_mcp.graph import normalize_return_format, query_note_graph
from flit_mcp.note_response import (
    DEFAULT_LIST_SNIPPET_CHARS,
    ReturnMode,
    normalize_return_mode,
    shape_note_detail_dict,
    shape_note_dict,
)
from flit_mcp.router_setup import flit_mcp_router
from flit_mcp.serialize import dump_model, dump_models
from flit_mcp.server_info import MCP_MAX_BATCH_NOTE_IDS
from flit_mcp.tool_meta import TOOL_META, search_tool_metas
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
    get_note_or_404,
    get_notes_by_ids,
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
    delete_relationship_for_user as delete_relationship_for_user_svc,
    filter_relationships_with_active_peers,
    list_relationships_for_note,
)
from service.user import get_user

SortByField = Literal["updated_at", "created_at", "title"]
SortOrder = Literal["asc", "desc"]


def _parse_optional_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _normalize_sort_by(value: str) -> SortByField:
    if value not in ("updated_at", "created_at", "title"):
        raise ValidationError("sort_by must be one of: updated_at, created_at, title")
    return value  # type: ignore[return-value]


def _normalize_sort_order(value: str) -> SortOrder:
    if value not in ("asc", "desc"):
        raise ValidationError("sort_order must be asc or desc")
    return value  # type: ignore[return-value]


async def _get_owned_note(db: AsyncSession, note_id: int, user_id: int) -> Note:
    try:
        return await get_note_or_404(db, note_id, user_id)
    except NotFoundError:
        raise note_not_found(note_id) from None


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
    filtered_rels = await filter_relationships_with_active_peers(
        db, note_id, user_id, relationships_raw
    )
    relationships = [RelationshipRead.model_validate(r) for r in filtered_rels]

    return NoteDetailRead(
        **NoteRead.model_validate(note).model_dump(),
        categories=categories,
        relationships=relationships,
    )


@flit_mcp_router.tool()
async def search_tools(
    query: Annotated[
        str,
        Field(
            description=(
                "Natural language or keywords describing the capability you need "
                "(e.g. 'create note', 'graph', 'categories')."
            ),
            min_length=1,
        ),
    ],
    group: Annotated[
        str | None,
        Field(
            description=(
                "Optional category filter: discovery, notes, categories, "
                "relationships, note_categories, user."
            )
        ),
    ] = None,
    limit: Annotated[
        int, Field(description="Maximum tools to return (1–50).", ge=1, le=50)
    ] = 10,
) -> list[dict[str, Any]]:
    """Find relevant MCP tools without loading full input schemas.

    Requires read scope. Prefer this for progressive discovery before tools/list
    or GET /mcp/catalog?detail=full. Returns only tools visible for the current
    token scope (write tools omitted for read-only tokens).
    """
    ctx = get_current_mcp_auth()
    descriptions = {
        name: meta.short_description for name, meta in TOOL_META.items()
    }
    return search_tool_metas(
        query,
        group=group,
        limit=limit,
        allow_write=ctx.allows_write(),
        descriptions=descriptions,
    )


@flit_mcp_router.tool()
async def list_notes(
    skip: Annotated[int, Field(description="Number of notes to skip for pagination.", ge=0)] = 0,
    limit: Annotated[
        int, Field(description="Maximum notes to return (1–1000).", ge=1, le=1000)
    ] = 100,
    category_name: Annotated[
        str | None,
        Field(description="Exact category name filter."),
    ] = None,
    search: Annotated[
        str | None,
        Field(description="Full-text search query (prefix, substring, fuzzy)."),
    ] = None,
    pinned_only: Annotated[
        bool, Field(description="When true, return only pinned notes.")
    ] = False,
    updated_after: Annotated[
        str | None,
        Field(description="Include notes updated at or after this ISO datetime."),
    ] = None,
    updated_before: Annotated[
        str | None,
        Field(description="Include notes updated at or before this ISO datetime."),
    ] = None,
    sort_by: Annotated[
        str,
        Field(description="Sort field when not searching: updated_at, created_at, or title."),
    ] = "updated_at",
    sort_order: Annotated[
        str, Field(description="Sort direction: asc or desc.")
    ] = "desc",
    return_mode: Annotated[
        str,
        Field(description="Content shape: full, metadata (omit content), or snippet."),
    ] = "full",
    max_content_chars: Annotated[
        int | None,
        Field(description="Truncate content to this length (full/snippet modes)."),
    ] = None,
) -> list[dict[str, Any]]:
    """List notes for discovery before get_note or get_notes.

    Requires read scope. Returns only the authenticated user's notes.
    Use return_mode=metadata or snippet to reduce token usage in list responses.
    """
    ctx = get_current_mcp_auth()
    mode = normalize_return_mode(return_mode)
    limit = min(max(limit, 1), 1000)
    async with mcp_db_session() as db:
        notes = await get_notes_by_user(
            db,
            ctx.user_id,
            skip=skip,
            limit=limit,
            category_name=category_name.strip() if category_name else None,
            search=search.strip() if search else None,
            pinned_only=pinned_only,
            updated_after=_parse_optional_datetime(updated_after),
            updated_before=_parse_optional_datetime(updated_before),
            sort_by=_normalize_sort_by(sort_by),
            sort_order=_normalize_sort_order(sort_order),
        )
        shaped = []
        for n in notes:
            d = dump_model(NoteRead.model_validate(n))
            shaped.append(
                shape_note_dict(
                    d,
                    return_mode=mode,
                    max_content_chars=max_content_chars,
                    snippet_chars=DEFAULT_LIST_SNIPPET_CHARS,
                )
            )
        return shaped


@flit_mcp_router.tool()
async def get_note(
    note_id: Annotated[int, Field(description="Note id from list_notes or get_notes.")],
    return_mode: Annotated[
        str,
        Field(description="Content shape: full, metadata (omit content), or snippet."),
    ] = "full",
    max_content_chars: Annotated[
        int | None,
        Field(description="Truncate content to this length (full/snippet modes)."),
    ] = None,
) -> dict[str, Any]:
    """Retrieve one note by id with categories and relationships.

    Requires read scope. Call after list_notes to fetch full detail for a candidate id.
    """
    ctx = get_current_mcp_auth()
    mode = normalize_return_mode(return_mode)
    async with mcp_db_session() as db:
        note = await _get_owned_note(db, note_id, ctx.user_id)
        detail = await _build_note_detail_read(db, note_id, ctx.user_id, note)
        return shape_note_detail_dict(
            dump_model(detail),
            return_mode=mode,
            max_content_chars=max_content_chars,
        )


@flit_mcp_router.tool()
async def get_notes(
    note_ids: Annotated[
        list[int],
        Field(description="Note ids to retrieve (max 50). Order is preserved for found notes."),
    ],
    include_categories: Annotated[
        bool, Field(description="Include linked categories per note.")
    ] = False,
    include_relationships: Annotated[
        bool, Field(description="Include peer relationships per note.")
    ] = False,
    return_mode: Annotated[
        str,
        Field(description="Content shape: full, metadata, or snippet."),
    ] = "full",
    max_content_chars: Annotated[
        int | None,
        Field(description="Truncate content to this length."),
    ] = None,
) -> dict[str, Any]:
    """Retrieve multiple notes by id in one call.

    Requires read scope. Returns found notes and missing_ids for ids not found or not owned.
    """
    ctx = get_current_mcp_auth()
    mode = normalize_return_mode(return_mode)
    if len(note_ids) > MCP_MAX_BATCH_NOTE_IDS:
        raise ValidationError(
            f"note_ids may contain at most {MCP_MAX_BATCH_NOTE_IDS} ids"
        )
    if not note_ids:
        return {"found": [], "missing_ids": []}

    unique_requested = list(dict.fromkeys(note_ids))
    async with mcp_db_session() as db:
        notes = await get_notes_by_ids(db, ctx.user_id, note_ids)
        found_ids = {n.id for n in notes}
        missing_ids = [nid for nid in unique_requested if nid not in found_ids]

        found: list[dict[str, Any]] = []
        for note in notes:
            if include_categories or include_relationships:
                detail = await _build_note_detail_read(
                    db, note.id, ctx.user_id, note
                )
                shaped = shape_note_detail_dict(
                    dump_model(detail),
                    return_mode=mode,
                    max_content_chars=max_content_chars,
                )
            else:
                shaped = shape_note_dict(
                    dump_model(NoteRead.model_validate(note)),
                    return_mode=mode,
                    max_content_chars=max_content_chars,
                )
            found.append(shaped)

        return {"found": found, "missing_ids": missing_ids}


@flit_mcp_router.tool()
async def query_graph(
    starting_id: Annotated[int, Field(description="Note id to begin graph traversal from.")],
    relation_type: Annotated[
        str | None,
        Field(
            description=(
                "Optional relationship type filter: FOLLOWS_ON, SIMILAR_TO, "
                "CONTRADICTS, REFERENCES, RELATED_TO."
            )
        ),
    ] = None,
    max_depth: Annotated[
        int, Field(description="Maximum hops from starting_id (1–3).", ge=1, le=3)
    ] = 2,
    limit: Annotated[
        int, Field(description="Maximum nodes to return (1–50).", ge=1, le=50)
    ] = 50,
    return_mode: Annotated[
        str,
        Field(description="Node content shape: full, metadata, or snippet."),
    ] = "snippet",
    max_content_chars: Annotated[
        int | None,
        Field(description="Truncate node content to this length."),
    ] = None,
    return_format: Annotated[
        str,
        Field(
            description=(
                'Result structure: "flat" (nodes + edges list, default) or '
                '"tree" (nested root with children by traversal path).'
            )
        ),
    ] = "flat",
) -> dict[str, Any]:
    """Traverse note relationships from a starting note via BFS.

    Requires read scope. Use return_format=flat (default) for efficient listing,
    or return_format=tree when relational depth and branching paths matter.
    Only includes notes owned by the authenticated user.
    """
    ctx = get_current_mcp_auth()
    mode = normalize_return_mode(return_mode)
    fmt = normalize_return_format(return_format)
    async with mcp_db_session() as db:
        await _get_owned_note(db, starting_id, ctx.user_id)
        return await query_note_graph(
            db,
            ctx.user_id,
            starting_id,
            relation_type=relation_type,
            max_depth=max_depth,
            limit=limit,
            return_mode=mode,
            return_format=fmt,
            max_content_chars=max_content_chars,
        )


@flit_mcp_router.tool()
async def create_note(
    title: Annotated[str, Field(description="Note title.", min_length=1)],
    content: Annotated[str, Field(description="Note body content.", min_length=1)],
    pinned: Annotated[bool, Field(description="Pin the note for priority listing.")] = False,
    color: Annotated[str, Field(description="Display color (hex or name).")] = "",
) -> dict[str, Any]:
    """Create a new note owned by the authenticated user.

    Requires read write scope. Notes are always created as BASE type.
    When to use: capture new knowledge before linking categories or relationships.
    Prerequisite: none. On not-found later, verify ids via list_notes.
    """
    ctx = get_current_mcp_auth()
    require_mcp_write(ctx)
    body = NoteCreateRequest(
        title=title,
        content=content,
        type=NoteType.BASE,
        pinned=pinned,
        color=color,
    )
    async with mcp_db_session() as db:
        note_create = NoteCreate(**body.model_dump(), user_id=ctx.user_id)
        note = await create_note_svc(db, note_create)
        return dump_model(NoteRead.model_validate(note))


@flit_mcp_router.tool()
async def update_note(
    note_id: Annotated[int, Field(description="Note id to update.")],
    title: Annotated[str | None, Field(description="New title (omit to leave unchanged).")] = None,
    content: Annotated[
        str | None, Field(description="New content — replaces entire body.")
    ] = None,
    pinned: Annotated[bool | None, Field(description="New pinned state.")] = None,
    color: Annotated[str | None, Field(description="New display color.")] = None,
) -> dict[str, Any]:
    """Update note fields. Requires read write scope. Only provided fields are changed.

    When to use: rename, recolor, pin, or replace the full body.
    To add text without replacing the body, use append_to_note instead.
    Error hint: if the note is missing, verify the id via list_notes.
    """
    ctx = get_current_mcp_auth()
    require_mcp_write(ctx)
    async with mcp_db_session() as db:
        await _get_owned_note(db, note_id, ctx.user_id)
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
async def append_to_note(
    note_id: Annotated[int, Field(description="Note id to append to.")],
    content: Annotated[str, Field(description="Text to append to the note body.", min_length=1)],
    separator: Annotated[
        str, Field(description="String inserted between existing and new content.")
    ] = "\n\n",
) -> dict[str, Any]:
    """Append text to a note without replacing the full content.

    Requires read write scope. When to use: logs, meeting notes, or incremental capture.
    Prerequisite: note_id from list_notes / create_note. Prefer over update_note when
    preserving existing body text.
    """
    ctx = get_current_mcp_auth()
    require_mcp_write(ctx)
    async with mcp_db_session() as db:
        note = await _get_owned_note(db, note_id, ctx.user_id)
        new_content = note.content + separator + content
        updated = await update_note_svc(
            db, note_id, NoteUpdate(content=new_content)
        )
        return dump_model(NoteRead.model_validate(updated))


@flit_mcp_router.tool()
async def delete_note(
    note_id: Annotated[int, Field(description="Note id to soft-delete.")],
) -> dict[str, bool]:
    """Soft-delete a note. Requires read write scope.

    When to use: permanently hide a note from listings. Verify note_id via list_notes first.
    """
    ctx = get_current_mcp_auth()
    require_mcp_write(ctx)
    async with mcp_db_session() as db:
        await delete_note_svc(db, note_id, ctx.user_id)
        return {"deleted": True}


@flit_mcp_router.tool()
async def list_categories(
    skip: Annotated[int, Field(description="Categories to skip.", ge=0)] = 0,
    limit: Annotated[
        int, Field(description="Maximum categories to return (1–1000).", ge=1, le=1000)
    ] = 100,
) -> list[dict[str, Any]]:
    """List categories for the authenticated user. Requires read scope.

    When to use: discover category ids before link_note_to_category or filtering list_notes.
    """
    ctx = get_current_mcp_auth()
    limit = min(max(limit, 1), 1000)
    async with mcp_db_session() as db:
        cats = await get_all_categories(db, ctx.user_id, skip=skip, limit=limit)
        return dump_models([CategoryRead.model_validate(c) for c in cats])


@flit_mcp_router.tool()
async def get_category(
    category_id: Annotated[int, Field(description="Category id.")],
) -> dict[str, Any]:
    """Retrieve a category by id. Requires read scope.

    Prerequisite: category_id from list_categories. Error if missing or not owned.
    """
    ctx = get_current_mcp_auth()
    async with mcp_db_session() as db:
        cat = await get_category_or_404(db, category_id, ctx.user_id)
        return dump_model(CategoryRead.model_validate(cat))


@flit_mcp_router.tool()
async def create_category(
    name: Annotated[str, Field(description="Category name.", min_length=1)],
) -> dict[str, Any]:
    """Create a category. Requires read write scope.

    When to use: introduce a new organization label before linking notes to it.
    """
    ctx = get_current_mcp_auth()
    require_mcp_write(ctx)
    async with mcp_db_session() as db:
        cat = await create_category_svc(db, CategoryCreate(name=name), ctx.user_id)
        return dump_model(CategoryRead.model_validate(cat))


@flit_mcp_router.tool()
async def update_category(
    category_id: Annotated[int, Field(description="Category id to rename.")],
    name: Annotated[str, Field(description="New category name.", min_length=1)],
) -> dict[str, Any]:
    """Rename a category. Requires read write scope.

    Prerequisite: category_id from list_categories. Does not move notes.
    """
    ctx = get_current_mcp_auth()
    require_mcp_write(ctx)
    async with mcp_db_session() as db:
        cat = await update_category_svc(
            db, category_id, CategoryUpdate(name=name), ctx.user_id
        )
        return dump_model(CategoryRead.model_validate(cat))


@flit_mcp_router.tool()
async def delete_category(
    category_id: Annotated[int, Field(description="Category id to delete.")],
) -> dict[str, bool]:
    """Delete a category. Requires read write scope.

    When to use: remove an unused label. Verify category_id via list_categories first.
    """
    ctx = get_current_mcp_auth()
    require_mcp_write(ctx)
    async with mcp_db_session() as db:
        await delete_category_svc(db, category_id, ctx.user_id)
        return {"deleted": True}


@flit_mcp_router.tool()
async def list_relationships(
    note_id: Annotated[int, Field(description="Note id whose relationships to list.")],
    skip: Annotated[int, Field(description="Relationships to skip.", ge=0)] = 0,
    limit: Annotated[
        int, Field(description="Maximum relationships to return.", ge=1, le=1000)
    ] = 100,
) -> list[dict[str, Any]]:
    """List relationships for one note (1-hop adjacency). Requires read scope.

    When to use: inspect direct links before query_graph multi-hop traversal.
    Prerequisite: note_id from list_notes.
    """
    ctx = get_current_mcp_auth()
    async with mcp_db_session() as db:
        await _get_owned_note(db, note_id, ctx.user_id)
        rels = await list_relationships_for_note(db, note_id, skip=skip, limit=limit)
        return dump_models([RelationshipRead.model_validate(r) for r in rels])


@flit_mcp_router.tool()
async def create_relationship(
    note_a_id: Annotated[int, Field(description="First note id.")],
    note_b_id: Annotated[int, Field(description="Second note id.")],
    type: Annotated[
        str,
        Field(
            description=(
                "Relationship type: FOLLOWS_ON, SIMILAR_TO, CONTRADICTS, "
                "REFERENCES, or RELATED_TO."
            )
        ),
    ] = "RELATED_TO",
) -> dict[str, Any]:
    """Create a relationship between two notes. Requires read write scope.

    When to use: connect related knowledge after create_note / list_notes.
    Both notes must be owned; verify ids via list_notes if the call fails.
    """
    ctx = get_current_mcp_auth()
    require_mcp_write(ctx)
    async with mcp_db_session() as db:
        if type not in RelationshipType.__members__:
            raise ValidationError(
                "type must be one of: FOLLOWS_ON, SIMILAR_TO, CONTRADICTS, "
                "REFERENCES, RELATED_TO"
            )
        rel_type = RelationshipType(type)
        rel = await create_relationship_svc(
            db,
            RelationshipCreate(
                note_a_id=note_a_id,
                note_b_id=note_b_id,
                type=rel_type,
            ),
            ctx.user_id,
        )
        return dump_model(RelationshipRead.model_validate(rel))


@flit_mcp_router.tool()
async def delete_relationship(
    note_a_id: Annotated[int, Field(description="First note id of the relationship.")],
    note_b_id: Annotated[int, Field(description="Second note id of the relationship.")],
) -> dict[str, bool]:
    """Delete a relationship between two notes. Requires read write scope.

    Prerequisite: note ids from list_relationships or query_graph.
    """
    ctx = get_current_mcp_auth()
    require_mcp_write(ctx)
    async with mcp_db_session() as db:
        await delete_relationship_for_user_svc(
            db, note_a_id, note_b_id, ctx.user_id
        )
        return {"deleted": True}


@flit_mcp_router.tool()
async def list_note_categories(
    note_id: Annotated[int, Field(description="Note id whose categories to list.")],
) -> list[dict[str, Any]]:
    """List categories linked to a note. Requires read scope.

    When to use: inspect organization before linking or unlinking categories.
    """
    ctx = get_current_mcp_auth()
    async with mcp_db_session() as db:
        await _get_owned_note(db, note_id, ctx.user_id)
        cats = await list_categories_for_note(db, note_id)
        owned = [c for c in cats if c.user_id == ctx.user_id]
        return dump_models([CategoryRead.model_validate(c) for c in owned])


@flit_mcp_router.tool()
async def link_note_to_category(
    note_id: Annotated[int, Field(description="Note id to link.")],
    category_id: Annotated[int, Field(description="Category id to link to.")],
) -> dict[str, Any]:
    """Link a note to a category. Requires read write scope.

    When to use: organize after create_note. Prerequisite: ids from list_notes and
    list_categories (or create_category).
    """
    ctx = get_current_mcp_auth()
    require_mcp_write(ctx)
    async with mcp_db_session() as db:
        await _get_owned_note(db, note_id, ctx.user_id)
        await get_category_or_404(db, category_id, ctx.user_id)
        link = await link_note_category(
            db,
            NoteCategoryCreate(note_id=note_id, category_id=category_id),
            ctx.user_id,
        )
        return dump_model(NoteCategoryRead.model_validate(link))


@flit_mcp_router.tool()
async def unlink_note_from_category(
    note_id: Annotated[int, Field(description="Note id to unlink.")],
    category_id: Annotated[int, Field(description="Category id to remove.")],
) -> dict[str, bool]:
    """Remove a note–category link. Requires read write scope.

    Prerequisite: confirm the link via list_note_categories first.
    """
    ctx = get_current_mcp_auth()
    require_mcp_write(ctx)
    async with mcp_db_session() as db:
        await _get_owned_note(db, note_id, ctx.user_id)
        await get_category_or_404(db, category_id, ctx.user_id)
        await unlink_note_category(db, note_id, category_id)
        return {"deleted": True}


@flit_mcp_router.tool()
async def get_user_profile() -> dict[str, Any]:
    """Get the authenticated user's profile and subscription summary. Requires read scope.

    When to use: check entitlement_active before heavy write workflows.
    """
    ctx = get_current_mcp_auth()
    async with mcp_db_session() as db:
        user = await get_user(db, ctx.user_id)
        if not user:
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
