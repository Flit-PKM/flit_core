from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class TokenRequest(BaseModel):
    grant_type: str = Field(
        ...,
        description="OAuth2 grant type. Use 'refresh_token' for token refresh.",
        examples=["refresh_token"],
    )
    refresh_token: Optional[str] = Field(
        None,
        description="Refresh token (required when grant_type is 'refresh_token')",
        examples=["refresh_token_abc123", None],
    )


class TokenResponse(BaseModel):
    access_token: str = Field(
        ...,
        description="OAuth2 access token for API authentication",
        examples=["eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."],
    )
    token_type: str = Field(
        "Bearer",
        description="Token type, always 'Bearer'",
        examples=["Bearer"],
    )
    expires_in: int = Field(
        ...,
        description="Access token expiration time in seconds",
        examples=[3600, 7200],
    )
    refresh_token: Optional[str] = Field(
        None,
        description="Refresh token for obtaining new access tokens",
        examples=["refresh_token_abc123", None],
    )
    scope: Optional[str] = Field(
        None,
        description="Space-separated list of granted scopes",
        examples=["read write", None],
    )


class RevokeRequest(BaseModel):
    token: str = Field(
        ...,
        description="Token to revoke (access token or refresh token)",
        examples=["access_token_abc123", "refresh_token_xyz789"],
    )
    token_type_hint: Optional[str] = Field(
        None,
        description="Hint about token type: 'access_token' or 'refresh_token' (optional but recommended)",
        examples=["access_token", "refresh_token", None],
    )
