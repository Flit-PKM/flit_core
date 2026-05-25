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


class McpOAuthClientRegistrationRequest(BaseModel):
    client_name: str
    redirect_uris: list[str]
    logo_uri: str | None = None
    token_endpoint_auth_method: str = "none"
    grant_types: list[str] | None = None
    response_types: list[str] | None = None


class McpOAuthClientRegistrationResponse(BaseModel):
    client_id: str
    client_name: str
    redirect_uris: list[str]
    token_endpoint_auth_method: str = "none"
    grant_types: list[str] = Field(
        default_factory=lambda: ["authorization_code", "refresh_token"]
    )
    response_types: list[str] = Field(default_factory=lambda: ["code"])
    client_id_issued_at: int
    client_secret_expires_at: int = 0
