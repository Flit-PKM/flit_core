from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from auth.dependencies import get_current_active_user
from database.session import get_async_session
from exceptions import NotFoundError
from logging_config import get_logger
from models.user import User
from schemas.connected_app import ConnectedAppRead, ConnectedAppUpdate
from service.app import get_app_by_slug
from service.connected_app import (
    get_connected_app,
    get_user_connected_apps,
    revoke_connected_app,
    update_connected_app,
)

logger = get_logger(__name__)

router = APIRouter(
    prefix="/connected-apps",
    tags=["connected-apps"],
)


def _app_read_from_connected_app(ca) -> ConnectedAppRead:
    app = get_app_by_slug(ca.app_slug)
    return ConnectedAppRead(
        id=ca.id,
        app_slug=ca.app_slug,
        app_name=app.name if app else None,
        user_id=ca.user_id,
        device_name=ca.device_name,
        platform=ca.platform,
        app_version=ca.app_version,
        is_active=ca.is_active,
        created_at=ca.created_at,
        updated_at=ca.updated_at,
    )


@router.get("", response_model=list[ConnectedAppRead])
async def list_connected_apps(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
) -> list[ConnectedAppRead]:
    """List all connected apps for the current user."""
    connected_apps = await get_user_connected_apps(db, current_user.id)
    return [_app_read_from_connected_app(ca) for ca in connected_apps]


@router.get("/{connected_app_id}", response_model=ConnectedAppRead)
async def get_connected_app_detail(
    connected_app_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
) -> ConnectedAppRead:
    """Get a specific connected app."""
    connected_app = await get_connected_app(db, connected_app_id, current_user.id)
    if not connected_app:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Connected app not found",
        )
    return _app_read_from_connected_app(connected_app)


@router.patch("/{connected_app_id}", response_model=ConnectedAppRead)
async def update_connected_app_route(
    connected_app_id: int,
    data: ConnectedAppUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
) -> ConnectedAppRead:
    """Update a connected app (device_name and/or is_active)."""
    try:
        connected_app = await update_connected_app(
            db,
            connected_app_id,
            current_user.id,
            device_name=data.device_name,
            is_active=data.is_active,
        )
    except NotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Connected app not found",
        )
    return _app_read_from_connected_app(connected_app)


@router.delete(
    "/{connected_app_id}",
    response_model=ConnectedAppRead,
    status_code=status.HTTP_200_OK,
)
async def delete(
    connected_app_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
) -> ConnectedAppRead:
    """Revoke/deactivate a connected app and return its final state."""
    try:
        connected_app = await revoke_connected_app(db, connected_app_id, current_user.id)
    except NotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Connected app not found",
        )
    return _app_read_from_connected_app(connected_app)
