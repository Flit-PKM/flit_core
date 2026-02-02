from typing import List, Optional, Union, Dict, Any
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.superuser import Superuser
from models.user import ColorScheme, User
from schemas.user import UserCreate, UserUpdate, UserRead
from exceptions import NotFoundError, AuthenticationError
from logging_config import get_logger
from auth.password import get_password_hash, verify_password

logger = get_logger(__name__)


async def create_user(
    session: AsyncSession, 
    user_data: Union[UserCreate, Dict[str, Any]]
) -> User:
    if hasattr(user_data, 'model_dump'):
        # It's a Pydantic model
        user_dict = user_data.model_dump()
    else:
        # It's already a dictionary
        user_dict = user_data

    # Normalize email to lowercase and strip whitespace
    if 'email' in user_dict:
        user_dict['email'] = user_dict['email'].lower().strip()

    # Superuser is managed only via the superusers table; never set from creation dict
    user_dict.pop("is_superuser", None)

    logger.debug(f"Creating user with email: {user_dict.get('email')}")
    db_user = User(**user_dict)
    session.add(db_user)
    await session.flush()
    await session.refresh(db_user)
    logger.info(f"User created successfully: {db_user.id}")
    return db_user

async def get_user(session: AsyncSession, user_id: int) -> User:
    result = await session.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()

async def get_user_by_email(session: AsyncSession, email: str) -> Optional[User]:
    # Normalize email to lowercase and strip whitespace for case-insensitive lookup
    normalized_email = email.lower().strip()
    logger.debug(f"Looking up user by email (normalized): {normalized_email}")
    result = await session.execute(
        select(User).where(func.lower(User.email) == normalized_email)
    )
    user = result.scalar_one_or_none()
    if user:
        logger.debug(f"User found: {user.id} - {user.email}")
    else:
        logger.debug(f"User not found for email: {normalized_email}")
    return user

async def get_all_users(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 10,
) -> List[User]:
    result = await db.execute(select(User).offset(skip).limit(limit))
    return result.scalars().all()

async def update_user(
    db: AsyncSession,
    user_id: int,
    user: UserUpdate,
) -> User:
    logger.debug(f"Updating user {user_id}")
    result = await db.execute(select(User).where(User.id == user_id))
    db_user = result.scalar_one_or_none()
    if not db_user:
        logger.warning(f"User not found for update: {user_id}")
        raise NotFoundError("User not found")
    
    user_dict = user.model_dump(exclude_unset=True)
    
    # Extract and verify current_password (required for all updates)
    current_password = user_dict.pop('current_password', None)
    if not current_password:
        logger.warning(f"Update attempt without current_password for user {user_id}")
        raise AuthenticationError("Current password is required")
    
    # Verify current password before allowing any updates
    if not verify_password(current_password, db_user.password_hash):
        logger.warning(f"Update attempt with incorrect current_password for user {user_id}")
        raise AuthenticationError("Current password is incorrect")
    
    # Handle password hashing if password is provided
    if 'password' in user_dict:
        password = user_dict.pop('password')
        user_dict['password_hash'] = get_password_hash(password)
    
    # Normalize email to lowercase and strip whitespace if it's being updated
    if 'email' in user_dict:
        user_dict['email'] = user_dict['email'].lower().strip()
    
    # Whitelist only allowed fields: username, email, password_hash, color_scheme
    allowed_fields = {'username', 'email', 'password_hash', 'color_scheme'}
    for field in allowed_fields:
        if field in user_dict:
            value = user_dict[field]
            if field == 'color_scheme' and value is not None:
                value = ColorScheme(value)
            setattr(db_user, field, value)
    
    logger.info(f"User updated successfully: {user_id}")
    return db_user

async def grant_superuser(
    db: AsyncSession,
    user_id: int,
    granted_by_id: int | None = None,
) -> User:
    """Grant superuser privilege to a user. Idempotent if already a superuser."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundError("User not found")
    existing = await db.execute(select(Superuser).where(Superuser.user_id == user_id))
    if existing.scalar_one_or_none():
        logger.debug(f"User {user_id} already has superuser privilege")
        return user
    superuser_row = Superuser(user_id=user_id, granted_by=granted_by_id)
    db.add(superuser_row)
    await db.flush()
    await db.refresh(user)
    logger.info(f"Superuser privilege granted to user {user_id} by {granted_by_id}")
    return user


async def revoke_superuser(db: AsyncSession, user_id: int) -> User:
    """Revoke superuser privilege from a user. Idempotent if not a superuser."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundError("User not found")
    existing = await db.execute(select(Superuser).where(Superuser.user_id == user_id))
    row = existing.scalar_one_or_none()
    if row:
        await db.delete(row)
        await db.flush()
        await db.refresh(user)
        logger.info(f"Superuser privilege revoked from user {user_id}")
    return user


async def delete_user(
    db: AsyncSession,
    user_id: int,
) -> None:
    """Soft-delete a user by setting is_active=False. Idempotent if already inactive."""
    logger.debug(f"Soft-deleting user {user_id}")
    result = await db.execute(select(User).where(User.id == user_id))
    db_user = result.scalar_one_or_none()
    if not db_user:
        logger.warning(f"User not found for deletion: {user_id}")
        raise NotFoundError("User not found")
    db_user.is_active = False
    await db.flush()
    logger.info(f"User soft-deleted (is_active=False): {user_id}")