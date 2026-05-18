from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class McpApiKeyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    scope: str = Field(
        default="read",
        description='Either "read" or "read write"',
    )


class McpApiKeyCreated(BaseModel):
    id: int
    name: str
    key_prefix: str
    scopes: str
    api_key: str = Field(..., description="Plaintext key; shown only once")
    created_at: datetime


class McpApiKeyRead(BaseModel):
    id: int
    name: str
    key_prefix: str
    scopes: str
    created_at: datetime
    last_used_at: datetime | None

    model_config = {"from_attributes": True}
