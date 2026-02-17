"""Verification token utilities for email verification flow."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt

from config import settings

_VERIFY_TOKEN_TYPE = "email_verify"


def create_verification_token(user_id: int) -> str:
    """Create a signed verification token for the given user. Token is valid for VERIFY_EMAIL_EXPIRE_HOURS."""
    expire_delta = timedelta(hours=settings.VERIFY_EMAIL_EXPIRE_HOURS)
    expire = datetime.now(timezone.utc) + expire_delta
    to_encode = {
        "sub": str(user_id),
        "type": _VERIFY_TOKEN_TYPE,
        "exp": expire,
        "jti": secrets.token_urlsafe(16),
    }
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def verify_verification_token(token: str) -> Optional[int]:
    """Decode and validate a verification token. Returns user_id if valid, else None."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if payload.get("type") != _VERIFY_TOKEN_TYPE:
            return None
        sub = payload.get("sub")
        if sub is None:
            return None
        return int(sub)
    except (JWTError, ValueError, TypeError):
        return None
