"""Schemas for password reset endpoints."""

from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class PasswordResetRequest(BaseModel):
    """Request body for POST /password-reset/request."""

    email: EmailStr = Field(..., description="Email address to send reset link to")
    cf_turnstile_response: Optional[str] = Field(
        None,
        description="Cloudflare Turnstile response token (required when TURNSTILE_SECRET is set)",
    )


class PasswordResetRequestResponse(BaseModel):
    """Response for POST /password-reset/request."""

    sent: bool = Field(
        ...,
        description="Always true on success; false when not configured or cooldown",
    )
    detail: Optional[str] = Field(
        None,
        description="Error message when sent=false",
    )


class PasswordResetConfirm(BaseModel):
    """Request body for POST /password-reset/confirm."""

    token: str = Field(..., description="Password reset token from email link")
    new_password: str = Field(
        ...,
        min_length=8,
        description="New password (minimum 8 characters)",
    )


class PasswordResetConfirmResponse(BaseModel):
    """Response for POST /password-reset/confirm."""

    success: bool = Field(..., description="Whether password was updated")
    detail: Optional[str] = Field(
        None,
        description="Error message when success=false",
    )
