"""Verification service: send verification email and consume verification tokens."""

from __future__ import annotations

import time
from typing import Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.verify_token import create_verification_token, verify_verification_token
from config import settings
from exceptions import ValidationError
from logging_config import get_logger
from models.user import User
from service.email import send_email
from public_url import public_base_url
from service.user import get_user

logger = get_logger(__name__)

# ponytail: process-local cooldown dict (multi-worker bypass + unbounded growth); use Redis/DB when scaling.
_verification_cooldown: dict[int, float] = {}


async def send_verification_email(db: AsyncSession, user: User) -> Tuple[bool, Optional[str]]:
    """
    Send a verification email to the user.

    Returns:
        Tuple of (sent, detail). sent=True when email was sent or user already verified.
        sent=False with detail when base URL unset, cooldown, or send failed.
    """
    try:
        base_url = public_base_url()
    except ValidationError:
        logger.error("PUBLIC_BASE_URL not configured; cannot send verification email")
        return False, "Verification is not configured"

    if user.is_verified:
        logger.info("User %s already verified; skipping email", user.id)
        return True, None

    # Check cooldown
    now = time.time()
    cooldown_seconds = settings.VERIFY_EMAIL_RESEND_COOLDOWN_MINUTES * 60
    last_sent = _verification_cooldown.get(user.id)
    if last_sent is not None and (now - last_sent) < cooldown_seconds:
        logger.info("Verification email cooldown for user %s", user.id)
        return False, "Please wait before requesting another email"

    token = create_verification_token(user.id)
    verify_link = f"{base_url}/api/verify/{token}/confirm"

    subject = "Verify your Flit email address"
    body_text = (
        f"Hi {user.username or user.email},\n\n"
        f"Please verify your email address by clicking the link below:\n\n"
        f"{verify_link}\n\n"
        f"This link expires in {settings.VERIFY_EMAIL_EXPIRE_HOURS} hours.\n\n"
        f"If you did not request this, you can ignore this email.\n\n"
        f"— Flit"
    )
    body_html = (
        f"<p>Hi {user.username or user.email},</p>\n"
        f"<p>Please verify your email address by clicking the link below:</p>\n"
        f"<p><a href=\"{verify_link}\">{verify_link}</a></p>\n"
        f"<p>This link expires in {settings.VERIFY_EMAIL_EXPIRE_HOURS} hours.</p>\n"
        f"<p>If you did not request this, you can ignore this email.</p>\n"
        f"<p>— Flit</p>"
    )

    ok = await send_email(
        to=user.email,
        subject=subject,
        body_text=body_text,
        body_html=body_html,
    )
    if ok:
        _verification_cooldown[user.id] = now
        logger.info("Verification email sent to user %s", user.id)
        return True, None
    return False, "Failed to send verification email"


async def consume_verification_token(db: AsyncSession, token: str) -> bool:
    """
    Validate the verification token and set user.is_verified = True.

    Returns True if token was valid and user was updated (or already verified).
    Returns False if token was invalid or expired.
    """
    user_id = verify_verification_token(token)
    if user_id is None:
        logger.warning("Invalid or expired verification token")
        return False

    user = await get_user(db, user_id)
    if not user:
        logger.warning("Verification token references non-existent user %s", user_id)
        return False

    if user.is_verified:
        logger.info("User %s already verified; idempotent success", user_id)
        return True

    user.is_verified = True
    await db.flush()
    logger.info("User %s email verified successfully", user_id)
    return True
