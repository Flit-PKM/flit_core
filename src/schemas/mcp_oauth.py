from __future__ import annotations

from pydantic import BaseModel, Field


class McpOAuthTokenResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    refresh_token: str
    scope: str


class McpOAuthRevokeResponse(BaseModel):
    revoked: bool = Field(..., description="True if a token was revoked")
