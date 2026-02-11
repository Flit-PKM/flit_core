"""Schemas for access code create and activate endpoints."""

from pydantic import BaseModel, Field


class AccessCodeCreateResponse(BaseModel):
    """Response when a superuser creates a new access code."""

    code: str = Field(..., description="The code to share (single-use)")
    period_weeks: int = Field(..., description="Duration in weeks from activation")
    includes_encryption: bool = Field(..., description="Whether the code grants encryption tier")


class AccessCodeActivateRequest(BaseModel):
    """Request body for POST /access-codes/activate."""

    code: str = Field(..., min_length=1, description="The access code to activate")


class AccessCodeActivateResponse(BaseModel):
    """Response when a user successfully activates a code."""

    expires_at: str = Field(..., description="When the grant expires (ISO 8601)")
    includes_encryption: bool = Field(..., description="Whether the grant includes encryption")
