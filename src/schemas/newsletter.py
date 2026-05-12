"""Admin newsletter campaign schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class NewsletterCampaignCreate(BaseModel):
    subject: str = Field(..., min_length=1, max_length=500)
    body_text: str = Field(..., min_length=1)
    body_html: Optional[str] = None


class NewsletterCampaignUpdate(BaseModel):
    subject: Optional[str] = Field(None, min_length=1, max_length=500)
    body_text: Optional[str] = Field(None, min_length=1)
    body_html: Optional[str] = None


class NewsletterCampaignRead(BaseModel):
    id: int
    subject: str
    body_text: str
    body_html: Optional[str]
    status: str
    scheduled_at: Optional[datetime]
    sent_at: Optional[datetime]
    created_by: Optional[int]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class NewsletterScheduleRequest(BaseModel):
    scheduled_at: datetime = Field(..., description="UTC (or tz-aware) time to send")
