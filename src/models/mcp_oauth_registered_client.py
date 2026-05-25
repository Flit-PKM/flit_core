from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class McpOAuthRegisteredClient(Base):
    __tablename__ = "mcp_oauth_registered_clients"

    client_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    owner_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
    )
    client_name: Mapped[str] = mapped_column(String(255), nullable=False)
    redirect_uris_json: Mapped[str] = mapped_column(Text, nullable=False)
    logo_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    exact_redirect_match: Mapped[bool] = mapped_column(
        Boolean(), nullable=False, default=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False)
