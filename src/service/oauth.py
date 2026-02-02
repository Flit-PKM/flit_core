from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.jwt import create_access_token
from config import settings
from exceptions import AuthenticationError
from logging_config import get_logger
from models.oauth_access_token import OAuthAccessToken
from models.oauth_refresh_token import OAuthRefreshToken

logger = get_logger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc_aware(dt: datetime) -> datetime:
    """Return dt as timezone-aware UTC (e.g. for SQLite-naive datetimes)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


async def issue_tokens_for_connected_app(
    session: AsyncSession,
    connected_app_id: int,
    user_id: int,
    scopes: str = "read write",
) -> tuple[OAuthAccessToken, OAuthRefreshToken]:
    """Create access + refresh tokens for a connected app (e.g. after connection-code exchange)."""
    expires_delta = timedelta(minutes=settings.OAUTH_ACCESS_TOKEN_EXPIRE_MINUTES)
    token_data = {
        "sub": str(user_id),
        "connected_app_id": connected_app_id,
        "scopes": scopes,
    }
    access_token_jwt = create_access_token(token_data, expires_delta=expires_delta)
    expires_at = (datetime.now(timezone.utc) + expires_delta).replace(tzinfo=None)
    access_token = OAuthAccessToken(
        token=access_token_jwt,
        connected_app_id=connected_app_id,
        user_id=user_id,
        scopes=scopes,
        expires_at=expires_at,
        created_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    session.add(access_token)
    await session.flush()

    refresh_token_str = secrets.token_urlsafe(32)
    refresh_expires_at = (datetime.now(timezone.utc) + timedelta(
        days=settings.OAUTH_REFRESH_TOKEN_EXPIRE_DAYS
    )).replace(tzinfo=None)
    refresh_token = OAuthRefreshToken(
        token=refresh_token_str,
        access_token_id=access_token.id,
        connected_app_id=connected_app_id,
        user_id=user_id,
        expires_at=refresh_expires_at,
        created_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    session.add(refresh_token)
    await session.flush()

    access_token.refresh_token_id = refresh_token.id
    await session.flush()

    logger.info(
        f"Issued tokens for connected_app_id={connected_app_id}, user_id={user_id}"
    )
    return access_token, refresh_token


async def refresh_access_token(
    session: AsyncSession,
    refresh_token_str: str,
) -> tuple[OAuthAccessToken, OAuthRefreshToken]:
    """Refresh an access token using a refresh token."""
    result = await session.execute(
        select(OAuthRefreshToken).where(OAuthRefreshToken.token == refresh_token_str)
    )
    refresh_token = result.scalar_one_or_none()

    if not refresh_token:
        raise AuthenticationError("Invalid refresh token")

    if refresh_token.revoked_at:
        raise AuthenticationError("Refresh token revoked")

    if _as_utc_aware(refresh_token.expires_at) < _utcnow():
        raise AuthenticationError("Refresh token expired")

    result = await session.execute(
        select(OAuthAccessToken).where(OAuthAccessToken.id == refresh_token.access_token_id)
    )
    old_access_token = result.scalar_one_or_none()

    if not old_access_token:
        raise AuthenticationError("Associated access token not found")

    old_access_token.revoked = True

    expires_delta = timedelta(minutes=settings.OAUTH_ACCESS_TOKEN_EXPIRE_MINUTES)
    token_data = {
        "sub": str(refresh_token.user_id),
        "connected_app_id": refresh_token.connected_app_id,
        "scopes": old_access_token.scopes,
    }
    access_token_jwt = create_access_token(token_data, expires_delta=expires_delta)

    expires_at = (datetime.now(timezone.utc) + expires_delta).replace(tzinfo=None)
    new_access_token = OAuthAccessToken(
        token=access_token_jwt,
        connected_app_id=refresh_token.connected_app_id,
        user_id=refresh_token.user_id,
        scopes=old_access_token.scopes,
        expires_at=expires_at,
        created_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    session.add(new_access_token)
    await session.flush()

    refresh_token.access_token_id = new_access_token.id
    new_access_token.refresh_token_id = refresh_token.id

    await session.flush()

    logger.info(
        f"Refreshed access token: connected_app_id={refresh_token.connected_app_id}, user_id={refresh_token.user_id}"
    )

    return new_access_token, refresh_token


async def revoke_token(
    session: AsyncSession,
    token: str,
    token_type_hint: Optional[str] = None,
) -> None:
    """Revoke an access or refresh token."""
    if token_type_hint == "refresh_token" or not token_type_hint:
        result = await session.execute(
            select(OAuthRefreshToken).where(OAuthRefreshToken.token == token)
        )
        refresh_token = result.scalar_one_or_none()
        if refresh_token and not refresh_token.revoked_at:
            refresh_token.revoked_at = datetime.now(timezone.utc).replace(tzinfo=None)
            result = await session.execute(
                select(OAuthAccessToken).where(
                    OAuthAccessToken.id == refresh_token.access_token_id
                )
            )
            access_token = result.scalar_one_or_none()
            if access_token:
                access_token.revoked = True
            await session.flush()
            logger.info(f"Revoked refresh token: {token[:10]}...")
            return

    result = await session.execute(
        select(OAuthAccessToken).where(OAuthAccessToken.token == token)
    )
    access_token = result.scalar_one_or_none()
    if access_token and not access_token.revoked:
        access_token.revoked = True
        if access_token.refresh_token_id:
            result = await session.execute(
                select(OAuthRefreshToken).where(
                    OAuthRefreshToken.id == access_token.refresh_token_id
                )
            )
            refresh_token = result.scalar_one_or_none()
            if refresh_token and not refresh_token.revoked_at:
                refresh_token.revoked_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await session.flush()
        logger.info(f"Revoked access token: {token[:10]}...")
        return

    logger.warning(f"Attempted to revoke unknown or already revoked token: {token[:10]}...")


async def validate_access_token(
    session: AsyncSession,
    token: str,
) -> Optional[tuple[int, int]]:
    """Validate access token and return (connected_app_id, user_id) if valid."""
    from jose import jwt

    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        connected_app_id = payload.get("connected_app_id")
        user_id = int(payload.get("sub"))

        if not connected_app_id or not user_id:
            return None

        result = await session.execute(
            select(OAuthAccessToken).where(OAuthAccessToken.token == token)
        )
        db_token = result.scalar_one_or_none()

        if db_token and db_token.revoked:
            return None

        return (connected_app_id, user_id)
    except Exception as e:
        logger.debug(f"Token validation failed: {e}")
        return None
