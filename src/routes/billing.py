"""Billing routes: Dodo Payments checkout and webhooks."""

import logging
from typing import Any, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from auth.dependencies import get_current_active_user
from config import settings
from database.session import get_async_session
from models.user import User
from service.billing import (
    BillingCompleteError,
    complete_subscription,
    create_checkout_session,
    get_plans,
    get_subscription_for_user,
    handle_webhook_event,
    is_billing_configured,
    is_checkout_configured,
    is_webhook_duplicate,
    mark_webhook_processed,
    unsafe_unwrap_webhook,
    unwrap_webhook,
    _webhook_event_log_summary,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/billing",
    tags=["billing"],
)


class CheckoutCreate(BaseModel):
    """Request to create a checkout session for a chosen plan (one of the 4 bundle products)."""

    product_id: str
    """Dodo product ID for the plan (from GET /billing/plans). One of the 4 Core+AI (with or without Encryption) products."""

    return_url: Optional[str] = None


class CheckoutResponse(BaseModel):
    """Checkout session response."""

    session_id: str
    checkout_url: str


class BillingCompleteRequest(BaseModel):
    """Request body for POST /billing/complete: frontend reports subscription success."""

    subscription_id: str
    status: str


class BillingCompleteResponse(BaseModel):
    """Response for POST /billing/complete."""

    ok: bool = True
    subscription_id: Optional[str] = None
    status: Optional[str] = None


class SubscriptionStatusResponse(BaseModel):
    """Current subscription status for the user."""

    status: Optional[str] = None
    current_period_end: Optional[str] = None
    dodo_subscription_id: Optional[str] = None


class AddonDetailResponse(BaseModel):
    """Addon details from Dodo Payments for display on the frontend."""

    id: str
    name: Optional[str] = None
    description: Optional[str] = None
    image: Optional[str] = None
    price: Optional[int] = None
    currency: Optional[str] = None
    tax_category: str = ""


class MeterDetailResponse(BaseModel):
    """Meter details from Dodo Payments for display on the frontend."""

    id: str
    name: Optional[str] = None
    description: Optional[str] = None
    event_name: Optional[str] = None
    aggregation: dict[str, Any] = {}
    measurement_unit: Optional[str] = None


PlanTypeLiteral = Literal[
    "monthly_core_ai",
    "monthly_core_ai_encryption",
    "annual_core_ai",
    "annual_core_ai_encryption",
]


class PlanDetailResponse(BaseModel):
    """Plan/product details from Dodo Payments for display on the frontend."""

    product_id: str
    name: Optional[str] = None
    description: Optional[str] = None
    image: Optional[str] = None
    is_recurring: bool = False
    price: dict[str, Any] = {}
    metadata: dict[str, str] = {}
    tax_category: str = ""
    addons: List[AddonDetailResponse] = []
    meters: List[MeterDetailResponse] = []
    plan_type: Optional[PlanTypeLiteral] = None
    show_discounted_badge: bool = False
    includes_encryption: bool = False


@router.get("/plans", response_model=List[PlanDetailResponse])
async def list_plans() -> List[PlanDetailResponse]:
    """
    Return available subscription plans with details (name, description, price, etc.) from Dodo Payments.
    Results are cached in-memory for 5 minutes. Returns empty list when billing is not configured.
    """
    try:
        plans = await get_plans()
    except Exception as e:
        logger.exception("Failed to load plans: %s", e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to load plans",
        ) from e
    return [PlanDetailResponse(**p) for p in plans]


@router.post("/checkout", response_model=CheckoutResponse)
async def create_checkout(
    body: CheckoutCreate,
    current_user: User = Depends(get_current_active_user),
) -> CheckoutResponse:
    """Create a Dodo Checkout Session for the subscription plan. Returns URL to redirect the user."""
    if not body.product_id or not body.product_id.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="product_id is required and cannot be empty",
        )
    if not is_checkout_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Billing is not configured",
        )
    try:
        result = await create_checkout_session(
            user_id=current_user.id,
            product_id=body.product_id.strip(),
            return_url=body.return_url,
        )
        return CheckoutResponse(
            session_id=result["session_id"],
            checkout_url=result["checkout_url"],
        )
    except ValueError as e:
        msg = str(e)
        if "not an allowed plan" in msg:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=msg,
            ) from e
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=msg,
        ) from e
    except Exception as e:
        logger.exception("Checkout session creation failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to create checkout session",
        )


@router.post("/complete", response_model=BillingCompleteResponse)
async def billing_complete(
    body: BillingCompleteRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_session),
) -> BillingCompleteResponse:
    """
    Receive frontend notification that a subscription has succeeded.
    Verifies subscription_id and status with Dodo, ensures it belongs to the current user, and upserts PlanSubscription.
    """
    try:
        await complete_subscription(
            db=db,
            user_id=current_user.id,
            subscription_id=body.subscription_id,
            status=body.status,
        )
    except BillingCompleteError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e
    return BillingCompleteResponse(ok=True, subscription_id=body.subscription_id, status=body.status)


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

    try:
        event = await unwrap_webhook(raw_body, headers, secret)
    except Exception as e:
        logger.warning(
            "Dodo webhook signature verification failed: %s",
            e,
            exc_info=True,
        )
        try:
            parsed = await unsafe_unwrap_webhook(raw_body)
            summary = _webhook_event_log_summary(parsed)
            logger.info(
                "Dodo webhook payload (unsafe_unwrap) for diagnostics: %s",
                summary,
            )
        except Exception as parse_err:
            logger.warning(
                "Dodo webhook unsafe_unwrap also failed: %s",
                parse_err,
                exc_info=True,
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid signature",
        )

    webhook_id = headers["webhook-id"]
    if is_webhook_duplicate(webhook_id):
        return {"received": True}

    mark_webhook_processed(webhook_id)
    await handle_webhook_event(db, event)
    return {"received": True}
