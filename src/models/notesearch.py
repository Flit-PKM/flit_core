from __future__ import annotations

from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class NoteSearch(Base):
    """Search index for non-encrypted notes. One row per note; hard-deleted when note is soft-deleted."""

    __tablename__ = "notesearch"

    note_id: Mapped[int] = mapped_column(
        ForeignKey("notes.id"),
        primary_key=True,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
