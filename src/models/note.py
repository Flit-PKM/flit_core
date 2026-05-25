from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, Enum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class NoteType(StrEnum):
    INSIGHT = "INSIGHT"
    SUMMARY = "SUMMARY"
    BASE = "BASE"


class Note(Base):
    __tablename__ = "notes"
    AppType = Enum("Flit", "Still", name="app_type")

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[NoteType] = mapped_column(
        String(20), nullable=False, index=True, default=NoteType.BASE
    )
    version: Mapped[int] = mapped_column(nullable=False, default=1)
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    color: Mapped[str] = mapped_column(String, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False, onupdate=func.now()
    )

    is_deleted: Mapped[bool] = mapped_column(default=False, nullable=False, index=True)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("connected_apps.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )