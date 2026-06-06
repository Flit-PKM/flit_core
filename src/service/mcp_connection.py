from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import NotFoundError
from flit_mcp.oauth.cimd import resolve_oauth_client
from models.mcp_access_token import McpAccessToken
from models.mcp_refresh_token import McpRefreshToken


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _resolve_client_name(
    session: AsyncSession,
    *,
    client_id: str | None,
    client_name: str | None,
) -> str | None:
    if client_name:
        return client_name
    if not client_id:
        return None
    client = await resolve_oauth_client(session, client_id)
    return client.name if client else client_id


async def list_mcp_connections(
    session: AsyncSession,
    user_id: int,
) -> list[McpRefreshToken]:
    now = _utcnow_naive()
    result = await session.execute(
        select(McpRefreshToken)
        .where(
            McpRefreshToken.user_id == user_id,
            McpRefreshToken.revoked_at.is_(None),
            McpRefreshToken.expires_at > now,
        )
        .order_by(McpRefreshToken.created_at.desc())
    )
    return list(result.scalars().all())


async def connection_to_read(
    session: AsyncSession,
    row: McpRefreshToken,
) -> dict:
    return {
        "id": row.id,
        "client_id": row.client_id,
        "client_name": await _resolve_client_name(
            session,
            client_id=row.client_id,
            client_name=row.client_name,
        ),
        "scopes": row.scopes,
        "created_at": row.created_at,
        "expires_at": row.expires_at,
    }


async def revoke_mcp_connection(
    session: AsyncSession,
    *,
    user_id: int,
    connection_id: int,
) -> None:
    result = await session.execute(
        select(McpRefreshToken).where(
            McpRefreshToken.id == connection_id,
            McpRefreshToken.user_id == user_id,
            McpRefreshToken.revoked_at.is_(None),
        )
    )
    refresh_row = result.scalar_one_or_none()
    if not refresh_row:
        raise NotFoundError("Connection not found")

    refresh_row.revoked_at = _utcnow_naive()

    access_result = await session.execute(
        select(McpAccessToken).where(
            McpAccessToken.refresh_token_id == connection_id,
            McpAccessToken.revoked.is_(False),
        )
    )
    for access_row in access_result.scalars().all():
        access_row.revoked = True

    await session.flush()
