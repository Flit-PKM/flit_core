from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, JSON, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from config import settings
from .base import Base


def _embedding_column_type():
    """Use pgvector on PostgreSQL, JSON on D1/SQLite (no native vector type)."""
    return Vector(1536) if settings.DB_BACKEND == "postgres" else JSON()


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    position_start: Mapped[int] = mapped_column(nullable=False)
    position_end: Mapped[int] = mapped_column(nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(
        _embedding_column_type(),
        nullable=True,
    )

    version: Mapped[int] = mapped_column(nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False, onupdate=func.now()
    )
    is_deleted: Mapped[bool] = mapped_column(default=False, nullable=False, index=True)

    note_id: Mapped[int] = mapped_column(
        ForeignKey("notes.id"), nullable=False, index=True
    )
