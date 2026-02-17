"""Password reset routes: request reset email and confirm with new password."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from turnstile import TurnstileVerificationError, verify_turnstile_token
from database.session import get_async_session
from logging_config import get_logger
from schemas.password_reset import (
    PasswordResetConfirm,
    PasswordResetConfirmResponse,
    PasswordResetRequest,
    PasswordResetRequestResponse,
)
from service.password_reset import confirm_password_reset, request_password_reset
from auth.password_reset_token import verify_password_reset_token

logger = get_logger(__name__)

router = APIRouter(
    prefix="/password-reset",
    tags=["password-reset"],
)


@router.post("/request", response_model=PasswordResetRequestResponse)
async def request_reset(
    request: Request,
    body: PasswordResetRequest,
    db: AsyncSession = Depends(get_async_session),
):
    """Request password reset email. Public. Always returns 200 to avoid user enumeration."""
    # Turnstile verification when TURNSTILE_SECRET is set
    if settings.TURNSTILE_SECRET:
        client_ip = request.headers.get("CF-Connecting-IP") or request.headers.get("X-Forwarded-For")
        if client_ip and "," in client_ip:
            client_ip = client_ip.split(",")[0].strip()
        if not client_ip and request.client:
            client_ip = request.client.host
        try:
            await verify_turnstile_token(body.cf_turnstile_response, client_ip)
        except TurnstileVerificationError as exc:
            logger.warning("Turnstile verification failed for password reset %s: %s", body.email, exc)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Human verification failed. Please try again.",
            )
    sent, detail = await request_password_reset(db, body.email)
    return PasswordResetRequestResponse(sent=sent, detail=detail)


@router.get("/{token}/confirm")
async def confirm_redirect(
    token: str,
):
    """Validate token and redirect to frontend reset-password page. Used by email links."""
    base = (settings.VERIFY_EMAIL_BASE_URL or "").strip().rstrip("/")
    if not base:
        return PasswordResetConfirmResponse(
            success=False,
            detail="Password reset is not configured",
        )

    user_id = verify_password_reset_token(token)
    if user_id is not None:
        return RedirectResponse(
            url=f"{base}/reset-password?token={token}",
            status_code=302,
        )
    return RedirectResponse(
        url=f"{base}/reset-password?error=expired",
        status_code=302,
    )


@router.post("/confirm", response_model=PasswordResetConfirmResponse)
async def confirm_reset(
    body: PasswordResetConfirm,
    db: AsyncSession = Depends(get_async_session),
):
    """Validate token and set new password. Public."""
    success = await confirm_password_reset(db, body.token, body.new_password)
    if success:
        return PasswordResetConfirmResponse(success=True)
    return PasswordResetConfirmResponse(
        success=False,
        detail="Invalid or expired reset link. Please request a new one.",
    )
