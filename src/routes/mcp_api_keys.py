from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from auth.dependencies import get_current_active_user
from config import settings
from database.session import get_async_session
from exceptions import NotFoundError, ValidationError
from models.user import User
from schemas.mcp_api_key import McpApiKeyCreate, McpApiKeyCreated, McpApiKeyRead
from service.mcp_api_key import create_mcp_api_key, list_mcp_api_keys, revoke_mcp_api_key

router = APIRouter(prefix="/mcp/api-keys", tags=["mcp-api-keys"])


def _require_mcp_enabled() -> None:
    if not settings.MCP_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MCP is not enabled on this server",
        )


@router.post("", response_model=McpApiKeyCreated, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    body: McpApiKeyCreate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
) -> McpApiKeyCreated:
    """Create a user-managed MCP API key (plaintext shown once). Requires JWT."""
    _require_mcp_enabled()
    try:
        row, plaintext = await create_mcp_api_key(
            db,
            user_id=current_user.id,
            name=body.name,
            scope=body.scope,
        )
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=e.detail) from e
    return McpApiKeyCreated(
        id=row.id,
        name=row.name,
        key_prefix=row.key_prefix,
        scopes=row.scopes,
        api_key=plaintext,
        created_at=row.created_at,
    )


@router.get("", response_model=List[McpApiKeyRead])
async def list_api_keys(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
) -> List[McpApiKeyRead]:
    """List MCP API keys for the current user (prefixes only). Requires JWT."""
    _require_mcp_enabled()
    rows = await list_mcp_api_keys(db, current_user.id)
    return [McpApiKeyRead.model_validate(r) for r in rows]


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_api_key(
    key_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
) -> None:
    """Revoke an MCP API key by id. Requires JWT."""
    _require_mcp_enabled()
    try:
        await revoke_mcp_api_key(db, user_id=current_user.id, key_id=key_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=e.detail) from e
    return None
