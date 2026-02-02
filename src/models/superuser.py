"""Superuser privilege: separate table so only explicit grant/revoke can change it."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class Superuser(Base):
    """Marks a user as superuser. Grant/revoke only via dedicated endpoints or migrations."""

    __tablename__ = "superusers"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    granted_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        nullable=False,
    )
    granted_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    user: Mapped["User"] = relationship(
        "User",
        back_populates="superuser_record",
        foreign_keys=[user_id],
    )
