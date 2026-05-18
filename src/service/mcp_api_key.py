from __future__ import annotations

import secrets
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.password import get_password_hash, verify_password
from exceptions import NotFoundError, ValidationError
from flit_mcp.scopes import READ_WRITE_SCOPE, SUPPORTED_SCOPES, normalize_requested_scope
from models.mcp_api_key import McpApiKey
from service.mcp_oauth import MCP_API_KEY_PREFIX


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def generate_api_key_plaintext() -> str:
    return f"{MCP_API_KEY_PREFIX}{secrets.token_urlsafe(32)}"


async def create_mcp_api_key(
    session: AsyncSession,
    *,
    user_id: int,
    name: str,
    scope: str,
) -> tuple[McpApiKey, str]:
    normalized = normalize_requested_scope(scope)
    if normalized not in SUPPORTED_SCOPES:
        raise ValidationError(f"scope must be one of: {', '.join(sorted(SUPPORTED_SCOPES))}")

    plaintext = generate_api_key_plaintext()
    prefix = plaintext[:16]
    row = McpApiKey(
        user_id=user_id,
        name=name.strip()[:255],
        key_hash=get_password_hash(plaintext),
        key_prefix=prefix,
        scopes=normalized,
        created_at=_utcnow_naive(),
        last_used_at=None,
        revoked_at=None,
    )
    session.add(row)
    await session.flush()
    return row, plaintext


async def list_mcp_api_keys(
    session: AsyncSession,
    user_id: int,
) -> list[McpApiKey]:
    result = await session.execute(
        select(McpApiKey)
        .where(McpApiKey.user_id == user_id, McpApiKey.revoked_at.is_(None))
        .order_by(McpApiKey.created_at.desc())
    )
    return list(result.scalars().all())


async def revoke_mcp_api_key(
    session: AsyncSession,
    *,
    user_id: int,
    key_id: int,
) -> None:
    result = await session.execute(
        select(McpApiKey).where(
            McpApiKey.id == key_id,
            McpApiKey.user_id == user_id,
            McpApiKey.revoked_at.is_(None),
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        raise NotFoundError("API key not found")
    row.revoked_at = _utcnow_naive()
    await session.flush()


async def validate_mcp_api_key(
    session: AsyncSession,
    bearer: str,
) -> tuple[int, str] | None:
    if not bearer.startswith(MCP_API_KEY_PREFIX):
        return None
    prefix = bearer[:16]
    result = await session.execute(
        select(McpApiKey).where(
            McpApiKey.key_prefix == prefix,
            McpApiKey.revoked_at.is_(None),
        )
    )
    for row in result.scalars().all():
        if verify_password(bearer, row.key_hash):
            row.last_used_at = _utcnow_naive()
            await session.flush()
            return row.user_id, row.scopes
    return None
