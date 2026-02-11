"""Access code models: single-use codes that grant time-limited Core+AI or Core+AI+Encryption access."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class AccessCode(Base):
    """Single-use code created by a superuser. Once activated, grants time-limited access to a user."""

    __tablename__ = "access_codes"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    period_weeks: Mapped[int] = mapped_column(Integer, nullable=False)
    includes_encryption: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    activated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    activated_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    grant = relationship(
        "AccessCodeGrant",
        back_populates="access_code",
        uselist=False,
        foreign_keys="AccessCodeGrant.access_code_id",
    )


class AccessCodeGrant(Base):
    """Grant created when a user activates an access code. Entitlement = any non-expired grant."""

    __tablename__ = "access_code_grants"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    access_code_id: Mapped[int] = mapped_column(
        ForeignKey("access_codes.id", ondelete="CASCADE"),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    includes_encryption: Mapped[bool] = mapped_column(Boolean, nullable=False)

    access_code = relationship(
        "AccessCode",
        back_populates="grant",
        foreign_keys=[access_code_id],
    )
