from __future__ import annotations

from typing import Optional

from config import settings
from schemas.app import AppRead


def get_allowed_apps() -> list[AppRead]:
    """Return app list from config (default or ALLOWED_APPS_JSON override)."""
    raw = settings.get_allowed_apps()
    return [AppRead(slug=a["slug"], name=a["name"]) for a in raw]


def get_app_by_slug(slug: str) -> Optional[AppRead]:
    """Return app by slug from config, or None if not found."""
    for a in get_allowed_apps():
        if a.slug == slug:
            return a
    return None
