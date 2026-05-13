"""Dodo webhook idempotency: one row per processed webhook-id header."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ProcessedDodoWebhook(Base):
    __tablename__ = "processed_dodo_webhooks"

    webhook_id: Mapped[str] = mapped_column(String(512), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
