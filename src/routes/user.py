from typing import List

from fastapi import APIRouter, Depends, HTTPException, status, Response, Request
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import get_async_session
from schemas.user import UserCreate, UserUpdate, UserRead, UserSubscriptionRead
from service.billing import get_subscription_for_user
from service.user import (
    create_user,
    get_user,
    get_all_users,
    update_user,
    delete_user,
    grant_superuser,
    revoke_superuser,
)
from auth.dependencies import get_current_active_user, get_current_superuser
from models.user import User
from logging_config import get_logger
from exceptions import NotFoundError

logger = get_logger(__name__)

# Router for admin operations (superuser only)
router = APIRouter(
    prefix="/users",
    tags=["users"],
)

# Router for current user operations (normal users)
current_user_router = APIRouter(
    prefix="/user",
    tags=["user"],
)

@router.get("/", response_model=List[UserRead])
async def get_all_users_endpoint(
    request: Request,
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_async_session),
    skip: int = 0,
    limit: int = 10,
):
    logger.info(
        f"GET /users/ - Superuser {current_user.id} fetching users list - "
        f"Path: {request.url.path}, Query: {request.url.query}, skip: {skip}, limit: {limit}"
    )
    users = await get_all_users(db, skip, limit)
    logger.info(f"GET /users/ - Returned {len(users)} users to superuser {current_user.id}")
    return users

@current_user_router.get("/", response_model=UserRead)
async def get_current_user_endpoint(
    request: Request,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Get the current authenticated user."""
    logger.info(
        f"GET /user - User {current_user.id} fetching their own user data - "
        f"Path: {request.url.path}, Query: {request.url.query}"
    )
    # Refresh user from database to ensure we have the latest data
    user = await get_user(db, current_user.id)

    if not user:
        logger.warning(f"GET /user - User {current_user.id} not found in database")
        raise NotFoundError("User not found")

    sub = await get_subscription_for_user(db, current_user.id)
    subscription_data = (
        UserSubscriptionRead(
            status=sub.status,
            current_period_end=sub.current_period_end.isoformat() if sub.current_period_end else None,
            dodo_subscription_id=sub.dodo_subscription_id,
        )
        if sub
        else None
    )
    base = UserRead.model_validate(user)
    logger.info(f"GET /user - User {current_user.id} fetched successfully")
    return base.model_copy(update={"subscription": subscription_data})

@router.get("/{user_id}", response_model=UserRead)
async def get_user_endpoint(
    request: Request,
    user_id: int,
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_async_session),
):
    """Get a specific user by ID. Superuser only."""
    logger.info(
        f"GET /users/{user_id} - Superuser {current_user.id} fetching user {user_id} - "
        f"Path: {request.url.path}, Query: {request.url.query}"
    )
    user = await get_user(db, user_id)

    if not user:
        logger.warning(f"GET /users/{user_id} - User {user_id} not found")
        raise NotFoundError("User not found")

    sub = await get_subscription_for_user(db, user_id)
    subscription_data = (
        UserSubscriptionRead(
            status=sub.status,
            current_period_end=sub.current_period_end.isoformat() if sub.current_period_end else None,
            dodo_subscription_id=sub.dodo_subscription_id,
        )
        if sub
        else None
    )
    base = UserRead.model_validate(user)
    logger.info(f"GET /users/{user_id} - User {user_id} fetched successfully by superuser {current_user.id}")
    return base.model_copy(update={"subscription": subscription_data})

@current_user_router.patch("/", response_model=UserRead)
async def update_current_user_endpoint(
    request: Request,
    user: UserUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Update the current authenticated user."""
    # Log request details (mask sensitive fields)
    user_dict = user.model_dump()
    log_dict = {k: "***" if "password" in k.lower() else v for k, v in user_dict.items()}
    
    logger.info(
        f"PATCH /user - User {current_user.id} updating their own user data - "
        f"Path: {request.url.path}, "
        f"Query: {request.url.query}, "
        f"Body fields: {list(user_dict.keys())}, "
        f"Body (masked): {log_dict}"
    )
    
    try:
        updated_user = await update_user(db, current_user.id, user)
        logger.info(f"PATCH /user - User {current_user.id} updated successfully")
        return updated_user
    except Exception as e:
        logger.error(
            f"PATCH /user - Error updating user {current_user.id}: {str(e)}",
            exc_info=True
        )
        raise

@router.patch("/{user_id}", response_model=UserRead)
async def update_user_endpoint(
    request: Request,
    user_id: int,
    user: UserUpdate,
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_async_session),
):
    """Update a specific user by ID. Superuser only."""
    # Log request details (mask sensitive fields)
    user_dict = user.model_dump()
    log_dict = {k: "***" if "password" in k.lower() else v for k, v in user_dict.items()}
    
    logger.info(
        f"PATCH /users/{user_id} - Superuser {current_user.id} updating user {user_id} - "
        f"Path: {request.url.path}, "
        f"Query: {request.url.query}, "
        f"Body fields: {list(user_dict.keys())}, "
        f"Body (masked): {log_dict}"
    )
    
    try:
        updated_user = await update_user(db, user_id, user)
        logger.info(f"PATCH /users/{user_id} - User {user_id} updated successfully by superuser {current_user.id}")
        return updated_user
    except Exception as e:
        logger.error(
            f"PATCH /users/{user_id} - Error updating user {user_id} by superuser {current_user.id}: {str(e)}",
            exc_info=True
        )
        raise

@router.post("/{user_id}/superuser", response_model=UserRead)
async def grant_superuser_endpoint(
    request: Request,
    user_id: int,
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_async_session),
):
    """Grant superuser privilege to a user. Superuser only."""
    logger.info(
        f"POST /users/{user_id}/superuser - Superuser {current_user.id} granting privilege - "
        f"Path: {request.url.path}"
    )
    user = await grant_superuser(db, user_id, granted_by_id=current_user.id)
    logger.info(f"POST /users/{user_id}/superuser - User {user_id} granted superuser by {current_user.id}")
    return user


@router.delete("/{user_id}/superuser", response_model=UserRead)
async def revoke_superuser_endpoint(
    request: Request,
    user_id: int,
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_async_session),
):
    """Revoke superuser privilege from a user. Superuser only."""
    logger.info(
        f"DELETE /users/{user_id}/superuser - Superuser {current_user.id} revoking privilege - "
        f"Path: {request.url.path}"
    )
    user = await revoke_superuser(db, user_id)
    logger.info(f"DELETE /users/{user_id}/superuser - User {user_id} revoked by {current_user.id}")
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user_endpoint(
    request: Request,
    user_id: int,
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_async_session),
):
    logger.info(
        f"DELETE /users/{user_id} - Superuser {current_user.id} deleting user {user_id} - "
        f"Path: {request.url.path}, Query: {request.url.query}"
    )
    await delete_user(db, user_id)
    logger.info(f"DELETE /users/{user_id} - User {user_id} deleted successfully by superuser {current_user.id}")
    return Response(status_code=status.HTTP_204_NO_CONTENT)