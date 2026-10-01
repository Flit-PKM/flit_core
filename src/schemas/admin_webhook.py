"""Schemas for admin outbound webhook configuration."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class AdminWebhookCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    url: str = Field(..., min_length=1, description="Destination webhook URL")
    events: list[str] = Field(
        ...,
        min_length=1,
        description="Event types this endpoint subscribes to",
    )
    enabled: bool = True


class AdminWebhookUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    url: Optional[str] = Field(None, min_length=1)
    events: Optional[list[str]] = Field(None, min_length=1)
    enabled: Optional[bool] = None


class AdminWebhookRead(BaseModel):
    id: int
    name: str
    url: str
    events: list[str]
    enabled: bool
    secret_set: bool
    secret_last4: Optional[str] = None
    created_by: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AdminWebhookWithSecret(AdminWebhookRead):
    """Create/rotate response: plaintext secret shown once."""

    secret: str = Field(
        ...,
        description="Standard Webhooks signing secret (whsec_…); shown only on create/rotate",
    )


class AdminWebhookTestRequest(BaseModel):
    event_type: Optional[str] = Field(
        None,
        description="Catalog event type to sample; defaults to webhook.test",
    )


class AdminWebhookTestResult(BaseModel):
    ok: bool
    event_type: str
    status_code: Optional[int] = None
    latency_ms: int
    error: Optional[str] = None


class AdminEventTypeList(BaseModel):
    event_types: list[str]
