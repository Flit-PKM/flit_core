"""Superuser reply to a feedback item."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class FeedbackResponse(Base):
    __tablename__ = "feedback_responses"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    feedback_id: Mapped[int] = mapped_column(
        ForeignKey("feedbacks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    author_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
