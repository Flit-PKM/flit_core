from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class SubscriptionCreate(BaseModel):
    """Payload for adding an email to the subscription list."""

    email: EmailStr = Field(
        ...,
        description="Email address to subscribe",
        examples=["user@example.com"],
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {"email": "user@example.com"},
        }
    )


class SubscriptionSubscribe(BaseModel):
    """Payload for POST /subscriptions: email + Turnstile token."""

    email: EmailStr = Field(
        ...,
        description="Email address to subscribe",
        examples=["user@example.com"],
    )
    cf_turnstile_response: Optional[str] = Field(
        None,
        description="Cloudflare Turnstile response token (cf-turnstile-response)",
        examples=["token-from-widget"],
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "email": "user@example.com",
                "cf_turnstile_response": "token-from-widget",
            },
        }
    )


class SubscriptionRead(BaseModel):
    """Subscription as returned by the API."""

    id: int = Field(..., description="Unique subscription identifier")
    email: str = Field(..., description="Subscribed email address")
    created_at: datetime = Field(
        ..., description="When the subscription was created"
    )

    model_config = ConfigDict(from_attributes=True)


class SubscriptionDelete(BaseModel):
    """Payload for DELETE /subscriptions: email to remove (must be on list)."""

    email: EmailStr = Field(
        ...,
        description="Email address to remove from the list",
        examples=["user@example.com"],
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {"email": "user@example.com"},
        }
    )
