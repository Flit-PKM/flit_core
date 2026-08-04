"""Public site URL for email links, MCP issuer, redirects."""

from __future__ import annotations

from config import settings
from exceptions import ValidationError


def public_base_url() -> str:
    """Public URL of this API (MCP OAuth issuer, email links, etc.)."""
    configured = (settings.PUBLIC_BASE_URL or "").strip().rstrip("/")
    if configured:
        return configured
    if settings.ENVIRONMENT == "development":
        return "http://127.0.0.1:8000"
    if settings.ENVIRONMENT == "test":
        return "http://testserver"
    raise ValidationError(
        "PUBLIC_BASE_URL must be set when ENVIRONMENT is production"
    )
