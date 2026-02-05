from typing import NamedTuple, Optional, Tuple
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import get_async_session
from models.user import User
from auth.jwt import verify_token
from service.billing import require_active_subscription
from service.oauth import validate_access_token
from service.user import get_user, get_user_by_email

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
    """Require an active subscription for sync routes. Raises 403 when billing is configured and user has no active subscription."""
    await require_active_subscription(db, oauth_ctx.user_id)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_async_session)
) -> User:
    """Get the current authenticated user from JWT token."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    token = credentials.credentials
    username = verify_token(token)
    if username is None:
        raise credentials_exception

    # Get user by email (username in JWT is email)
    user = await get_user_by_email(db, username)
    if user is None:
        raise credentials_exception

    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """Get the current active user."""
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user


async def get_current_superuser(
    current_user: User = Depends(get_current_active_user)
) -> User:
    """Get the current superuser. Raises 403 if user is not a superuser."""
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized. Superuser access required."
        )
    return current_user


async def get_current_oauth_connected_app(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_async_session),
) -> Tuple[int, int]:
    """Get the current OAuth connected app and user from token.
    
    Returns:
        Tuple of (connected_app_id, user_id)
    """
    token = credentials.credentials
    result = await validate_access_token(db, token)
    
    if not result:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    connected_app_id, user_id = result
    return connected_app_id, user_id


async def get_current_oauth_user(
    connected_app_and_user: Tuple[int, int] = Depends(get_current_oauth_connected_app),
    db: AsyncSession = Depends(get_async_session),
) -> User:
    """Get the current user from OAuth token."""
    _, user_id = connected_app_and_user
    user = await get_user(db, user_id)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user",
        )
    
    return user