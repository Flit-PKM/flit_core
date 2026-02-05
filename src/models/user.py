from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Optional

from sqlalchemy import Boolean, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .superuser import Superuser


class ColorScheme(StrEnum):
    """User preference for UI color scheme (light/dark/default)."""

    LIGHT = "light"
    DARK = "dark"
    DEFAULT = "default"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    username: Mapped[str] = mapped_column(nullable=False)
    email: Mapped[str] = mapped_column(unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True)
    is_verified: Mapped[bool] = mapped_column(default=False)
    superuser_record: Mapped[Optional[Superuser]] = relationship(
        "Superuser",
        back_populates="user",
        uselist=False,
        lazy="joined",
        foreign_keys=[Superuser.user_id],
    )
    color_scheme: Mapped[ColorScheme] = mapped_column(
        String(20), nullable=False, default=ColorScheme.DEFAULT
    )
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False, onupdate=func.now()
    )

    plan_subscription: Mapped[Optional["PlanSubscription"]] = relationship(
        "PlanSubscription",
        back_populates="user",
        uselist=False,
        lazy="selectin",
    )

    @property
    def is_superuser(self) -> bool:
        """True if this user has a row in the superusers table."""
        return self.superuser_record is not None
