from typing import NamedTuple

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt as jose_jwt
from sqlalchemy.ext.asyncio import AsyncSession

from auth.jwt import decode_login_token_claims
from database.session import get_async_session
from models.user import User
from service.entitlement import require_active_entitlement
from service.oauth import validate_access_token
from service.revoked_jwt import is_jti_revoked
from service.user import get_user_by_email

security = HTTPBearer()


class OAuthContext(NamedTuple):
    """OAuth token context for sync endpoints: (user_id, connected_app_id)."""

    user_id: int
    connected_app_id: int


async def get_sync_oauth_context(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_async_session),
) -> OAuthContext:
    """Get (user_id, connected_app_id) from OAuth token for sync routes. Single dependency for all sync endpoints."""
    token = credentials.credentials
    result = await validate_access_token(db, token)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    connected_app_id, user_id = result
    return OAuthContext(user_id=user_id, connected_app_id=connected_app_id)


async def require_active_subscription_for_sync(
    oauth_ctx: OAuthContext = Depends(get_sync_oauth_context),
    db: AsyncSession = Depends(get_async_session),
) -> None:
    """Require entitlement for sync routes. Raises 403 when billing is configured and user lacks it."""
    await require_active_entitlement(db, oauth_ctx.user_id)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_async_session),
) -> User:
    """Get the current authenticated user from JWT token.

    Login JWTs use email in ``sub``; OAuth/MCP tokens use user_id — do not reuse
    this dependency for those token types.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    token = credentials.credentials
    payload = decode_login_token_claims(token)
    if payload is None:
        raise credentials_exception

    # jti may not appear on all jwt.decode code paths; unverified claims are safe after verify above.
    raw_claims = jose_jwt.get_unverified_claims(token)
    jti = raw_claims.get("jti") or payload.get("jti")
    if not jti:
        raise credentials_exception
    revoked = await is_jti_revoked(db, str(jti))
    if revoked:
        raise credentials_exception

    username = payload.get("sub")
    if username is None or not isinstance(username, str):
        raise credentials_exception

    # Get user by email (username in JWT is email)
    user = await get_user_by_email(db, username)
    if user is None:
        raise credentials_exception

    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """Get the current active user."""
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user",
        )
    return current_user


async def get_current_superuser(
    current_user: User = Depends(get_current_active_user),
) -> User:
    """Get the current superuser. Raises 403 if user is not a superuser."""
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized. Superuser access required.",
        )
    return current_user
