from __future__ import annotations

from typing import Optional
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import NotFoundError
from logging_config import get_logger
from models.connected_app import ConnectedApp
from models.oauth_access_token import OAuthAccessToken
from models.oauth_refresh_token import OAuthRefreshToken

logger = get_logger(__name__)


async def create_connected_app_from_exchange(
    session: AsyncSession,
    user_id: int,
    app_slug: str,
    device_name: str,
    platform: str,
    app_version: str,
) -> ConnectedApp:
    """Create a connected app from connection-code exchange."""
    connected_app = ConnectedApp(
        user_id=user_id,
        app_slug=app_slug,
        device_name=device_name,
        platform=platform,
        app_version=app_version,
        is_active=True,
    )
    session.add(connected_app)
    await session.flush()
    await session.refresh(connected_app)
    logger.info(
        f"Created connected app from exchange: id={connected_app.id}, "
        f"user_id={user_id}, app_slug={app_slug}, device={device_name}"
    )
    return connected_app


async def get_user_connected_apps(
    session: AsyncSession,
    user_id: int,
) -> list[ConnectedApp]:
    """Get all connected apps for a user."""
    result = await session.execute(
        select(ConnectedApp)
        .where(ConnectedApp.user_id == user_id)
        .order_by(ConnectedApp.created_at.desc())
    )
    return list(result.scalars().all())


async def get_connected_app(
    session: AsyncSession,
    connected_app_id: int,
    user_id: int,
) -> Optional[ConnectedApp]:
    """Get a specific connected app, ensuring it belongs to the user."""
    result = await session.execute(
        select(ConnectedApp).where(
            ConnectedApp.id == connected_app_id,
            ConnectedApp.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def update_connected_app(
    session: AsyncSession,
    connected_app_id: int,
    user_id: int,
    *,
    device_name: Optional[str] = None,
    is_active: Optional[bool] = None,
) -> ConnectedApp:
    """Update a connected app (device_name and/or is_active)."""
    connected_app = await get_connected_app(session, connected_app_id, user_id)
    if not connected_app:
        raise NotFoundError("Connected app not found")

    if device_name is not None:
        connected_app.device_name = device_name
    if is_active is not None:
        connected_app.is_active = is_active

    await session.flush()
    await session.refresh(connected_app)
    logger.info(f"Updated connected app: id={connected_app_id}")
    return connected_app


async def revoke_connected_app(
    session: AsyncSession,
    connected_app_id: int,
    user_id: int,
) -> ConnectedApp:
    """Revoke/deactivate a connected app and invalidate its OAuth tokens."""
    connected_app = await get_connected_app(session, connected_app_id, user_id)
    if not connected_app:
        raise NotFoundError("Connected app not found")

    connected_app.is_active = False
    # Revoke all refresh tokens for this connected app + user
    result = await session.execute(
        select(OAuthRefreshToken).where(
            OAuthRefreshToken.connected_app_id == connected_app_id,
            OAuthRefreshToken.user_id == user_id,
            OAuthRefreshToken.revoked_at.is_(None),
        )
    )
    refresh_tokens = list(result.scalars().all())
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for refresh_token in refresh_tokens:
        refresh_token.revoked_at = now

    # Revoke all access tokens for this connected app + user
    result = await session.execute(
        select(OAuthAccessToken).where(
            OAuthAccessToken.connected_app_id == connected_app_id,
            OAuthAccessToken.user_id == user_id,
            OAuthAccessToken.revoked.is_(False),
        )
    )
    access_tokens = list(result.scalars().all())
    for access_token in access_tokens:
        access_token.revoked = True

    await session.flush()
    await session.refresh(connected_app)
    logger.info(f"Revoked connected app and tokens: id={connected_app_id}, user_id={user_id}")
    return connected_app
