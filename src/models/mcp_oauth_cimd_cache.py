from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class McpOAuthCimdCache(Base):
    __tablename__ = "mcp_oauth_cimd_cache"

    client_id_url: Mapped[str] = mapped_column(Text, primary_key=True)
    document_json: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False)
