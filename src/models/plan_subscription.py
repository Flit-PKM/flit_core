"""Plan subscription model for Dodo Payments subscription tracking."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class PlanSubscription(Base):
    """Dodo Payments subscription linked to a user (one active plan per user)."""

    __tablename__ = "plan_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    dodo_subscription_id: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False,
    )
    dodo_customer_id: Mapped[str] = mapped_column(
        String(255),
        index=True,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    current_period_end: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        nullable=False,
        onupdate=func.now(),
    )

    user = relationship(
        "User",
        back_populates="plan_subscription",
        foreign_keys=[user_id],
    )
