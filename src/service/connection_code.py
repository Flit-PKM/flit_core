from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from exceptions import ConflictError, ValidationError
from logging_config import get_logger
from models.connection_code import ConnectionCode

logger = get_logger(__name__)

# Readable alphanumeric, avoid 0/O/1/l, lowercase only for better UX
_CODE_ALPHABET = "23456789abcdefghjkmnpqrstuvwxyz"


def _generate_code() -> str:
    """Generate a short, readable connection code."""
    n = settings.CONNECTION_CODE_LENGTH
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(n))


async def create_connection_code(
    session: AsyncSession,
    user_id: int,
) -> ConnectionCode:
    """Create a generic connection code for a user. Returns the code entity."""
    if not user_id or user_id <= 0:
        raise ValidationError("Invalid user_id")

    max_retries = 5
    for _ in range(max_retries):
        code = _generate_code()
        existing = await session.execute(
            select(ConnectionCode).where(ConnectionCode.code == code)
        )
        if existing.scalar_one_or_none():
            continue

        expires_at = (datetime.now(timezone.utc) + timedelta(
            minutes=settings.CONNECTION_CODE_EXPIRE_MINUTES
        )).replace(tzinfo=None)
        row = ConnectionCode(
            code=code,
            user_id=user_id,
            app_slug=None,
            expires_at=expires_at,
        )
        session.add(row)
        await session.flush()
        await session.refresh(row)
        logger.info(f"Created connection code for user_id={user_id}")
        return row

    raise ValidationError("Failed to generate unique connection code")


async def consume_connection_code(
    session: AsyncSession,
    code: str,
) -> ConnectionCode:
    """
    Validate code, mark used, return the row.
    Raises ValidationError or ConflictError on failure.
    """
    if not code or not code.strip():
        raise ValidationError("connection_code is required")

    # Normalize code to lowercase for case-insensitive lookup
    normalized_code = code.strip().lower()
    stmt = select(ConnectionCode).where(ConnectionCode.code == normalized_code)
    dialect_name = session.get_bind().dialect.name
    if dialect_name != "sqlite":
        stmt = stmt.with_for_update(skip_locked=True)
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()

    if not row:
        raise ValidationError("Invalid connection code")

    if row.used_at is not None:
        raise ConflictError("Connection code already used")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    expires_at = row.expires_at
    # Normalize to naive UTC so we can compare (DB/driver may return naive or aware)
    if expires_at.tzinfo is not None:
        expires_at = expires_at.astimezone(timezone.utc).replace(tzinfo=None)
    if expires_at < now:
        raise ValidationError("Connection code expired")

    await session.execute(
        update(ConnectionCode)
        .where(ConnectionCode.id == row.id)
        .values(used_at=now)
    )
    await session.flush()
    await session.refresh(row)
    logger.info(f"Consumed connection code for user_id={row.user_id}")
    return row
