"""Access code service: create codes (superuser), activate (user), and check grants for entitlement."""

from __future__ import annotations

import secrets
import string
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import ConflictError, ValidationError
from models.access_code import AccessCode, AccessCodeGrant


# 8-character code: uppercase + digits, excluding ambiguous (0/O, 1/I/L)
_CODE_ALPHABET = string.ascii_uppercase + "23456789"
_CODE_LENGTH = 8


def _generate_code() -> str:
    """Return an 8-character code suitable for manual entry."""
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))


async def create_access_code(
    db: AsyncSession,
    period_weeks: int,
    created_by: int,
) -> AccessCode:
    """
    Create a new single-use access code. Caller must be a superuser.
    Returns the AccessCode with the code string to share.
    """
    if period_weeks < 1 or period_weeks > 52:
        raise ValidationError("period_weeks must be between 1 and 52")
    for _ in range(10):
        code = _generate_code()
        existing = await db.execute(select(AccessCode).where(AccessCode.code == code))
        if existing.scalar_one_or_none() is None:
            break
    else:
        raise ValidationError("Could not generate a unique code; try again")
    access_code = AccessCode(
        code=code,
        period_weeks=period_weeks,
        created_by=created_by,
    )
    db.add(access_code)
    await db.flush()
    await db.refresh(access_code)
    return access_code


async def get_access_code_by_code(db: AsyncSession, code: str) -> Optional[AccessCode]:
    """Return AccessCode by code string (trimmed), or None if not found."""
    trimmed = (code or "").strip()
    if not trimmed:
        return None
    result = await db.execute(select(AccessCode).where(AccessCode.code == trimmed))
    return result.scalar_one_or_none()


async def activate_code(
    db: AsyncSession,
    code: str,
    user_id: int,
) -> AccessCodeGrant:
    """
    Activate the code for the given user. Creates a grant and marks the code as used.
    Raises ValidationError if code is invalid or already used.
    """
    access_code = await get_access_code_by_code(db, code)
    if not access_code:
        raise ValidationError("Invalid or unknown code")
    if access_code.activated_at is not None:
        raise ConflictError("This code has already been used")
    if access_code.revoked_at is not None:
        raise ValidationError("This code has been revoked")
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(weeks=access_code.period_weeks)
    grant = AccessCodeGrant(
        user_id=user_id,
        access_code_id=access_code.id,
        expires_at=expires_at,
    )
    db.add(grant)
    access_code.activated_at = now
    access_code.activated_by = user_id
    await db.flush()
    await db.refresh(grant)
    return grant


async def get_active_access_grant(
    db: AsyncSession,
    user_id: int,
) -> Optional[AccessCodeGrant]:
    """
    Return a non-expired access grant for the user, if any.
    Returns the grant with the latest expires_at (best remaining period).
    """
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(AccessCodeGrant)
        .where(
            AccessCodeGrant.user_id == user_id,
            AccessCodeGrant.expires_at > now,
        )
        .order_by(AccessCodeGrant.expires_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def list_access_codes(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 50,
) -> list[AccessCode]:
    result = await db.execute(
        select(AccessCode)
        .order_by(AccessCode.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())


async def revoke_access_code(db: AsyncSession, code: str) -> AccessCode:
    """Mark an unused access code as revoked. Raises if unknown, used, or already revoked."""
    access_code = await get_access_code_by_code(db, code)
    if not access_code:
        raise ValidationError("Invalid or unknown code")
    if access_code.activated_at is not None:
        raise ConflictError("Cannot revoke a code that has already been used")
    if access_code.revoked_at is not None:
        return access_code
    access_code.revoked_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(access_code)
    return access_code
