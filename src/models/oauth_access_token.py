from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class OAuthAccessToken(Base):
    __tablename__ = "oauth_access_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[str] = mapped_column(Text, unique=True, nullable=False, index=True)
    connected_app_id: Mapped[int] = mapped_column(
        ForeignKey("connected_apps.id"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    scopes: Mapped[str] = mapped_column(String(255), nullable=False)  # Space-separated
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    refresh_token_id: Mapped[int | None] = mapped_column(
        ForeignKey("oauth_refresh_tokens.id", use_alter=True), nullable=True
    )
    revoked: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False)
