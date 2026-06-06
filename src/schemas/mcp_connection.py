from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class McpConnectionRead(BaseModel):
    id: int = Field(..., description="Refresh token row id (connection id)")
    client_id: str | None = Field(None, description="OAuth client id")
    client_name: str | None = Field(None, description="Display name of the connected client")
    scopes: str = Field(..., description='Granted scopes, e.g. "read" or "read write"')
    created_at: datetime
    expires_at: datetime

    model_config = {"from_attributes": True}
