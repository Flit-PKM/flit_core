"""Schemas for email verification endpoints."""

from typing import Optional

from pydantic import BaseModel, Field


class VerifySendResponse(BaseModel):
    """Response for GET /verify (send verification email)."""

    sent: bool = Field(..., description="Whether the verification email was sent")
    detail: Optional[str] = Field(
        None,
        description="Error or status message when sent=false",
    )


class VerifyTokenResponse(BaseModel):
    """Response for GET /verify/{token} (consume verification token)."""

    success: bool = Field(..., description="Whether verification succeeded")
    detail: Optional[str] = Field(
        None,
        description="Error message when success=false",
    )
