"""Per-user encryption key (DEK) stored encrypted under the server master key."""

from __future__ import annotations

from sqlalchemy import ForeignKey, SmallInteger, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class UserEncryptionKey(Base):
    """One row per user: encrypted data encryption key (DEK), stored as base64."""

    __tablename__ = "user_encryption_keys"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    encrypted_dek: Mapped[str] = mapped_column(Text, nullable=False)
    key_version: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)

    user = relationship("User", back_populates="encryption_key", foreign_keys=[user_id])
