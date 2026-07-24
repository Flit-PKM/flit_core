"""Superuser CRUD and test-fire for outbound admin webhooks."""

from typing import List, Optional

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from auth.dependencies import get_current_superuser
from database.session import get_async_session
from models.user import User
from openapi_responses import SUPERUSER
from schemas.admin_webhook import (
    AdminEventTypeList,
    AdminWebhookCreate,
    AdminWebhookRead,
    AdminWebhookTestRequest,
    AdminWebhookTestResult,
    AdminWebhookUpdate,
)
from service import admin_webhook as webhook_service

router = APIRouter(prefix="/admin/webhooks", tags=["admin"])


@router.get(
    "/event-types",
    response_model=AdminEventTypeList,
    responses=SUPERUSER,
)
async def list_event_types(
    current_user: User = Depends(get_current_superuser),
):
    """List catalog event types for UI pickers. Superuser only."""
    return AdminEventTypeList(
        event_types=sorted(webhook_service.ADMIN_EVENT_TYPES),
    )


@router.get("", response_model=List[AdminWebhookRead], responses=SUPERUSER)
async def list_webhooks(
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_async_session),
    skip: int = 0,
    limit: int = 100,
):
    """List configured admin webhooks (secrets masked). Superuser only."""
    rows = await webhook_service.list_webhooks(db, skip=skip, limit=limit)
    return [AdminWebhookRead(**webhook_service.webhook_to_read_dict(r)) for r in rows]


@router.post(
    "",
    response_model=AdminWebhookRead,
    status_code=status.HTTP_201_CREATED,
    responses=SUPERUSER,
)
async def create_webhook(
    body: AdminWebhookCreate,
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_async_session),
):
    """Create an admin webhook endpoint. Superuser only."""
    row = await webhook_service.create_webhook(
        db,
        name=body.name,
        url=body.url,
        events=body.events,
        secret=body.secret,
        enabled=body.enabled,
        created_by=current_user.id,
    )
    return AdminWebhookRead(**webhook_service.webhook_to_read_dict(row))


@router.get("/{webhook_id}", response_model=AdminWebhookRead, responses=SUPERUSER)
async def get_webhook(
    webhook_id: int,
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_async_session),
):
    """Get one admin webhook (secret masked). Superuser only."""
    row = await webhook_service.get_webhook(db, webhook_id)
    return AdminWebhookRead(**webhook_service.webhook_to_read_dict(row))


@router.patch("/{webhook_id}", response_model=AdminWebhookRead, responses=SUPERUSER)
async def update_webhook(
    webhook_id: int,
    body: AdminWebhookUpdate,
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_async_session),
):
    """Update an admin webhook. Superuser only."""
    row = await webhook_service.update_webhook(
        db,
        webhook_id,
        name=body.name,
        url=body.url,
        events=body.events,
        secret=body.secret,
        clear_secret=body.clear_secret,
        enabled=body.enabled,
    )
    return AdminWebhookRead(**webhook_service.webhook_to_read_dict(row))


@router.delete(
    "/{webhook_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=SUPERUSER,
)
async def delete_webhook(
    webhook_id: int,
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_async_session),
):
    """Delete an admin webhook. Superuser only."""
    await webhook_service.delete_webhook(db, webhook_id)


@router.post(
    "/{webhook_id}/test",
    response_model=AdminWebhookTestResult,
    responses=SUPERUSER,
)
async def test_webhook(
    webhook_id: int,
    body: Optional[AdminWebhookTestRequest] = None,
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_async_session),
):
    """
    Fire a test (or sample catalog) event to this endpoint only.
    Awaits delivery and returns status. Ignores enabled/event filters.
    """
    event_type = body.event_type if body else None
    result = await webhook_service.fire_test_event(db, webhook_id, event_type)
    return AdminWebhookTestResult(
        ok=result.ok,
        event_type=result.event_type,
        status_code=result.status_code,
        latency_ms=result.latency_ms,
        error=result.error,
    )
