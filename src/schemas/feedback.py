"""Schemas for feedback create and read endpoints."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class FeedbackCreate(BaseModel):
    """Payload for POST /feedback: content (required) and optional context."""

    content: str = Field(
        ...,
        description="Feedback content",
        min_length=1,
        examples=["This feature is great!"],
    )
    context: Optional[dict[str, Any]] = Field(
        None,
        description="Optional JSON context (e.g. page, version, source)",
        examples=[{"page": "settings", "version": "1.0.0"}],
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "content": "Love the new sync feature!",
                "context": {"source": "mobile", "app_version": "2.1.0"},
            },
        }
    )


class FeedbackRead(BaseModel):
    """Feedback as returned by the API."""

    id: int = Field(..., description="Unique feedback identifier")
    content: str = Field(..., description="Feedback content")
    context: Optional[dict[str, Any]] = Field(
        None, description="Optional JSON context"
    )
    created_at: datetime = Field(
        ..., description="When the feedback was created"
    )

    model_config = ConfigDict(from_attributes=True)
