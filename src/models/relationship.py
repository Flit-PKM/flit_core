from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class RelationshipType(StrEnum):
    FOLLOWS_ON = "FOLLOWS_ON"
    SIMILAR_TO = "SIMILAR_TO"
    CONTRADICTS = "CONTRADICTS"
    REFERENCES = "REFERENCES"
    RELATED_TO = "RELATED_TO"


class Relationship(Base):
    __tablename__ = "relationships"

    note_a_id: Mapped[int] = mapped_column(
        ForeignKey("notes.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    note_b_id: Mapped[int] = mapped_column(
        ForeignKey("notes.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    type: Mapped[RelationshipType] = mapped_column(
        String(20),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False, onupdate=func.now()
    )
    is_deleted: Mapped[bool] = mapped_column(default=False, nullable=False, index=True)
