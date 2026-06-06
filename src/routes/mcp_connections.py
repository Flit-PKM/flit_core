from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from auth.dependencies import get_current_active_user
from config import settings
from database.session import get_async_session
from exceptions import NotFoundError
from models.user import User
from schemas.mcp_connection import McpConnectionRead
from service.mcp_connection import (
    connection_to_read,
    list_mcp_connections,
    revoke_mcp_connection,
)

router = APIRouter(prefix="/mcp/connections", tags=["mcp-connections"])


def _require_mcp_enabled() -> None:
    if not settings.MCP_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MCP is not enabled on this server",
        )


@router.get("", response_model=List[McpConnectionRead])
async def list_connections(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
) -> List[McpConnectionRead]:
    """List active MCP OAuth sessions for the current user. Requires JWT."""
    _require_mcp_enabled()
    rows = await list_mcp_connections(db, current_user.id)
    reads = [await connection_to_read(db, row) for row in rows]
    return [McpConnectionRead.model_validate(r) for r in reads]


@router.delete("/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connection(
    connection_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
) -> None:
    """Revoke an MCP OAuth session (refresh + access tokens). Requires JWT."""
    _require_mcp_enabled()
    try:
        await revoke_mcp_connection(
            db,
            user_id=current_user.id,
            connection_id=connection_id,
        )
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=e.detail) from e
    return None
