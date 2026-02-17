"""Email verification routes: send verification email and consume token."""

from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from auth.dependencies import get_current_active_user
from config import settings
from database.session import get_async_session
from logging_config import get_logger
from models.user import User
from schemas.verify import VerifySendResponse, VerifyTokenResponse
from service.verification import consume_verification_token, send_verification_email

logger = get_logger(__name__)

router = APIRouter(
    prefix="/verify",
    tags=["verification"],
)


@router.get("", response_model=VerifySendResponse)
async def send_verification(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
):
    """Send verification email to the current user. Requires authentication."""
    logger.info("GET /verify - User %s requesting verification email", current_user.id)
    sent, detail = await send_verification_email(db, current_user)
    return VerifySendResponse(sent=sent, detail=detail)


@router.get("/{token}/confirm")
async def verify_token_confirm(
    token: str,
    db: AsyncSession = Depends(get_async_session),
):
    """Validate token and redirect to frontend with success/error query params. Used by email links."""
    base = (settings.VERIFY_EMAIL_BASE_URL or "").strip().rstrip("/")
    if not base:
        return VerifyTokenResponse(
            success=False,
            detail="Verification is not configured",
        )
    success = await consume_verification_token(db, token)
    if success:
        return RedirectResponse(url=f"{base}/verify?success=1", status_code=302)
    return RedirectResponse(url=f"{base}/verify?success=0&error=expired", status_code=302)


@router.get("/{token}", response_model=VerifyTokenResponse)
async def verify_token(
    token: str,
    db: AsyncSession = Depends(get_async_session),
):
    """Validate verification token and mark user as verified. Public endpoint."""
    success = await consume_verification_token(db, token)
    if success:
        return VerifyTokenResponse(success=True)
    return VerifyTokenResponse(success=False, detail="Invalid or expired verification link")
