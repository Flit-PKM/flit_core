"""Password reset service: request reset email and confirm with new password."""

from __future__ import annotations

import time
from typing import Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from auth.password import get_password_hash
from auth.password_reset_token import create_password_reset_token, verify_password_reset_token
from config import settings
from logging_config import get_logger
from models.user import User
from service.email import send_email
from service.user import get_user, get_user_by_email

logger = get_logger(__name__)

# In-memory cooldown: normalized_email -> last_sent timestamp (seconds since epoch)
_password_reset_cooldown: dict[str, float] = {}


async def request_password_reset(db: AsyncSession, email: str) -> Tuple[bool, Optional[str]]:
    """
    Send password reset email if user exists. Always returns (True, None) to avoid user enumeration.

    Returns:
        Tuple of (sent_ok, detail). sent_ok=True for success or when user not found (no leak).
        sent_ok=False with detail only when base URL unset or cooldown.
    """
    if not settings.VERIFY_EMAIL_BASE_URL or not settings.VERIFY_EMAIL_BASE_URL.strip():
        logger.error("VERIFY_EMAIL_BASE_URL not set; cannot send password reset email")
        return False, "Password reset is not configured"

    normalized_email = email.lower().strip()
    user = await get_user_by_email(db, normalized_email)
    if not user:
        logger.info("Password reset requested for unknown email (no leak)")
        return True, None

    if not user.is_verified:
        logger.info("Password reset skipped for unverified email (no leak)")
        return True, None

    # Check cooldown by email
    now = time.time()
    cooldown_seconds = settings.PASSWORD_RESET_COOLDOWN_MINUTES * 60
    last_sent = _password_reset_cooldown.get(normalized_email)
    if last_sent is not None and (now - last_sent) < cooldown_seconds:
        logger.info("Password reset cooldown for %s", normalized_email)
        return False, "Please wait before requesting another reset email"

    token = create_password_reset_token(user.id)
    base_url = settings.VERIFY_EMAIL_BASE_URL.strip().rstrip("/")
    reset_link = f"{base_url}/api/password-reset/{token}/confirm"

    subject = "Reset your Flit password"
    body_text = (
        f"Hi {user.username or user.email},\n\n"
        f"We received a request to reset your password. Click the link below to set a new one:\n\n"
        f"{reset_link}\n\n"
        f"This link expires in {settings.PASSWORD_RESET_EXPIRE_HOURS} hour(s).\n\n"
        f"If you did not request this, you can ignore this email. Your password will not change.\n\n"
        f"— Flit"
    )
    body_html = (
        f"<p>Hi {user.username or user.email},</p>\n"
        f"<p>We received a request to reset your password. Click the link below to set a new one:</p>\n"
        f"<p><a href=\"{reset_link}\">{reset_link}</a></p>\n"
        f"<p>This link expires in {settings.PASSWORD_RESET_EXPIRE_HOURS} hour(s).</p>\n"
        f"<p>If you did not request this, you can ignore this email. Your password will not change.</p>\n"
        f"<p>— Flit</p>"
    )

    ok = await send_email(
        to=user.email,
        subject=subject,
        body_text=body_text,
        body_html=body_html,
    )
    if ok:
        _password_reset_cooldown[normalized_email] = now
        logger.info("Password reset email sent to user %s", user.id)
        return True, None
    return False, "Failed to send password reset email"


async def confirm_password_reset(
    db: AsyncSession,
    token: str,
    new_password: str,
) -> bool:
    """
    Validate token and update user password. Returns True on success, False if invalid/expired.
    """
    user_id = verify_password_reset_token(token)
    if user_id is None:
        logger.warning("Invalid or expired password reset token")
        return False

    user = await get_user(db, user_id)
    if not user:
        logger.warning("Password reset token references non-existent user %s", user_id)
        return False

    user.password_hash = get_password_hash(new_password)
    await db.flush()
    logger.info("Password reset completed for user %s", user_id)
    return True
