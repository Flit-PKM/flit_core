"""Admin email template schemas."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class EmailTemplateUpdate(BaseModel):
    subject: Optional[str] = Field(None, min_length=1, max_length=500)
    body_text: Optional[str] = Field(None, min_length=1)
    body_html: Optional[str] = None
    enabled: Optional[bool] = None


class EmailTemplateRead(BaseModel):
    key: str
    description: str
    placeholders: list[str]
    subject: str
    body_text: str
    body_html: Optional[str]
    enabled: bool
    is_overridden: bool
