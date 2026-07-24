from __future__ import annotations

import json

from flit_mcp.auth.contextvar import get_current_mcp_auth
from flit_mcp.db import mcp_db_session
from flit_mcp.router_setup import flit_mcp_router
from flit_mcp.serialize import dump_model
from schemas.category import CategoryRead
from schemas.note import NoteRead
from service.access_code import get_active_access_grant
from service.billing import SUBSCRIPTION_STATUS_ACTIVE, get_subscription_for_user
from service.category import get_category_or_404
from service.note import get_note as get_note_row
from service.user import get_user

_JSON = "application/json"


@flit_mcp_router.resource("flit://user/profile", mime_type=_JSON)
async def resource_user_profile() -> str:
    """Authenticated user's profile summary (read scope)."""
    ctx = get_current_mcp_auth()
    async with mcp_db_session() as db:
        user = await get_user(db, ctx.user_id)
        if not user:
            from exceptions import NotFoundError

            raise NotFoundError("User not found")
        sub = await get_subscription_for_user(db, ctx.user_id)
        grant = await get_active_access_grant(db, ctx.user_id)
        payload = {
            "id": user.id,
            "email": user.email,
            "username": user.username,
            "is_active": user.is_active,
            "is_verified": user.is_verified,
            "entitlement_active": bool(
                grant or (sub and sub.status == SUBSCRIPTION_STATUS_ACTIVE)
            ),
        }
        return json.dumps(payload)


@flit_mcp_router.resource("flit://note/{note_id}", mime_type=_JSON)
async def resource_note(note_id: int) -> str:
    """Single note as JSON (read scope). Only notes you own."""
    ctx = get_current_mcp_auth()
    async with mcp_db_session() as db:
        note = await get_note_row(db, note_id)
        if not note or note.user_id != ctx.user_id:
            from exceptions import NotFoundError

            raise NotFoundError("Note not found")
        return json.dumps(dump_model(NoteRead.model_validate(note)))


@flit_mcp_router.resource("flit://category/{category_id}", mime_type=_JSON)
async def resource_category(category_id: int) -> str:
    """Single category as JSON (read scope)."""
    ctx = get_current_mcp_auth()
    async with mcp_db_session() as db:
        cat = await get_category_or_404(db, category_id, ctx.user_id)
        return json.dumps(dump_model(CategoryRead.model_validate(cat)))
