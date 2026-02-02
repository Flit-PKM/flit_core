from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from schemas.app import AppRead
from service.app import get_allowed_apps, get_app_by_slug

router = APIRouter(
    prefix="/apps",
    tags=["apps"],
)


@router.get("", response_model=list[AppRead])
async def list_apps() -> list[AppRead]:
    """List all available app types (from config)."""
    return get_allowed_apps()


@router.get("/by-slug/{slug}", response_model=AppRead)
async def get_app_by_slug_route(slug: str) -> AppRead:
    """Get app by slug from config."""
    app = get_app_by_slug(slug)
    if not app:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="App not found",
        )
    return app
