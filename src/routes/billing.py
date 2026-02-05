"""Billing routes: Dodo Payments checkout and webhooks."""

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from auth.dependencies import get_current_active_user
from config import settings
from database.session import get_async_session
from models.user import User
from service.billing import (
    create_checkout_session,
    get_subscription_for_user,
    handle_webhook_event,
    is_billing_configured,
    is_webhook_duplicate,
    mark_webhook_processed,
    verify_webhook_signature,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/billing",
    tags=["billing"],
)


class CheckoutCreate(BaseModel):
    """Optional return URL after checkout."""

    return_url: Optional[str] = None


class CheckoutResponse(BaseModel):
    """Checkout session response."""

    session_id: str
    checkout_url: str


class SubscriptionStatusResponse(BaseModel):
    """Current subscription status for the user."""

    status: Optional[str] = None
    current_period_end: Optional[str] = None
    dodo_subscription_id: Optional[str] = None


@router.post("/checkout", response_model=CheckoutResponse)
async def create_checkout(
    body: CheckoutCreate,
    current_user: User = Depends(get_current_active_user),
) -> CheckoutResponse:
    """Create a Dodo Checkout Session for the subscription plan. Returns URL to redirect the user."""
    if not is_billing_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Billing is not configured",
        )
    try:
        result = await create_checkout_session(
            user_id=current_user.id,
            return_url=body.return_url,
        )
        return CheckoutResponse(
            session_id=result["session_id"],
            checkout_url=result["checkout_url"],
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )
    except Exception as e:
        logger.exception("Checkout session creation failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to create checkout session",
        )


@router.get("/subscription", response_model=SubscriptionStatusResponse)
async def get_subscription(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
) -> SubscriptionStatusResponse:
    """Return the current user's subscription status (from PlanSubscription)."""
    sub = await get_subscription_for_user(db, current_user.id)
    if not sub:
        return SubscriptionStatusResponse(
            status=None,
            current_period_end=None,
            dodo_subscription_id=None,
        )
    return SubscriptionStatusResponse(
        status=sub.status,
        current_period_end=sub.current_period_end.isoformat() if sub.current_period_end else None,
        dodo_subscription_id=sub.dodo_subscription_id,
    )


@router.post("/webhooks/dodo")
async def dodo_webhook(
    request: Request,
    db: AsyncSession = Depends(get_async_session),
) -> dict[str, bool]:
    """
    Receive Dodo Payments webhooks (Standard Webhooks signed).
    Verify signature, enforce idempotency, then process the event.
    """
    secret = settings.DODO_PAYMENTS_WEBHOOK_SECRET
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook secret not configured",
        )

    raw_body = await request.body()
    headers = {
        "webhook-id": request.headers.get("webhook-id", ""),
        "webhook-signature": request.headers.get("webhook-signature", ""),
        "webhook-timestamp": request.headers.get("webhook-timestamp", ""),
    }

    if not verify_webhook_signature(raw_body, headers, secret):
        logger.warning("Dodo webhook signature verification failed")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid signature",
        )

    webhook_id = headers["webhook-id"]
    if is_webhook_duplicate(webhook_id):
        return {"received": True}

    try:
        event = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError as e:
        logger.warning("Dodo webhook invalid JSON: %s", e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON",
        )

    mark_webhook_processed(webhook_id)
    await handle_webhook_event(db, event)
    return {"received": True}
