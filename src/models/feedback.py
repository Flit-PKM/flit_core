from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Feedback(Base):
    """User feedback submission (public POST, superuser-only read/delete)."""

    __tablename__ = "feedbacks"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )
