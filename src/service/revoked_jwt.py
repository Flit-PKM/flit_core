"""Persist revoked login JWT `jti` until expiry."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from models.revoked_jwt import RevokedJwt


async def is_jti_revoked(db: AsyncSession, jti: str) -> bool:
    if not jti:
        return False
    r = await db.execute(text("SELECT 1 FROM revoked_jwts WHERE jti = :jti"), {"jti": jti})
    return r.scalar_one_or_none() is not None


async def revoke_jti(db: AsyncSession, jti: str, expires_at: datetime) -> None:
    """Record jti as revoked until expires_at (UTC-aware)."""
    if not jti:
        return
    row = RevokedJwt(jti=jti, expires_at=expires_at)
    db.add(row)
    await db.flush()
