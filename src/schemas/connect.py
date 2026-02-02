from __future__ import annotations

from pydantic import BaseModel, Field


class ConnectRequestCodeResponse(BaseModel):
    """Connection code issued to user."""

    connection_code: str = Field(
        ...,
        description="Short-lived code user enters in the app",
        examples=["ABC12345"],
    )
    expires_in: int = Field(
        ...,
        description="Seconds until code expires",
        examples=[600],
    )


class ConnectExchangeRequest(BaseModel):
    """App sends code + device metadata to exchange for tokens."""

    connection_code: str = Field(
        ...,
        description="Code from request-code flow",
        examples=["ABC12345"],
    )
    app_slug: str = Field(
        ...,
        description="App slug identifying which app is connecting (e.g. flit, still)",
        examples=["flit", "still"],
    )
    device_name: str = Field(
        ...,
        min_length=1,
        description="Device name (e.g. MacBook Pro)",
        examples=["MacBook Pro", "iPhone"],
    )
    platform: str = Field(
        ...,
        min_length=1,
        description="Platform (e.g. macOS, iOS)",
        examples=["macOS", "iOS", "Windows"],
    )
    app_version: str = Field(
        ...,
        min_length=1,
        description="App version (e.g. 1.2.0)",
        examples=["1.2.0", "2.0.1"],
    )


class ConnectExchangeResponse(BaseModel):
    """Tokens returned after successful exchange."""

    access_token: str = Field(..., description="Bearer token for API auth")
    token_type: str = Field(default="Bearer", description="Token type")
    expires_in: int = Field(..., description="Access token TTL in seconds")
    refresh_token: str = Field(..., description="Token to obtain new access tokens")
