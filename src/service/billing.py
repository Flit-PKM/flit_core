"""Billing service: Dodo Payments checkout and webhook handling."""

from __future__ import annotations

import asyncio
import hmac
import hashlib
import logging
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models.plan_subscription import PlanSubscription

logger = logging.getLogger(__name__)

SUBSCRIPTION_STATUS_ACTIVE = "active"

# In-memory set of processed webhook IDs for idempotency (single process).
# For multi-worker deployments, replace with a DB table or Redis.
_processed_webhook_ids: set[str] = set()
_MAX_CACHED_WEBHOOK_IDS = 10_000


def _get_dodo_client():
    """Return a configured Dodo Payments client (sync)."""
    from dodopayments import DodoPayments

    env = (settings.DODO_PAYMENTS_ENVIRONMENT or "test").lower()
    environment = "test_mode" if env == "test" else "live_mode"
    return DodoPayments(
        bearer_token=settings.DODO_PAYMENTS_API_KEY,
        environment=environment,
    )


def is_billing_configured() -> bool:
    """True if Dodo Payments API key and product ID are set."""
    return bool(
        settings.DODO_PAYMENTS_API_KEY
        and settings.DODO_PAYMENTS_SUBSCRIPTION_PRODUCT_ID
    )


async def create_checkout_session(
    user_id: int,
    return_url: Optional[str] = None,
) -> dict[str, str]:
    """
    Create a Dodo Checkout Session for the subscription product.
    Returns dict with session_id and checkout_url.
    """
    if not is_billing_configured():
        raise ValueError("Dodo Payments is not configured")

    def _create() -> dict[str, str]:
        client = _get_dodo_client()
        payload = {
            "product_cart": [
                {
                    "product_id": settings.DODO_PAYMENTS_SUBSCRIPTION_PRODUCT_ID,
                    "quantity": 1,
                }
            ],
            "metadata": {"user_id": str(user_id)},
        }
        if return_url:
            payload["return_url"] = return_url
        resp = client.checkout_sessions.create(**payload)
        return {
            "session_id": resp.session_id,
            "checkout_url": resp.checkout_url or "",
        }

    return await asyncio.to_thread(_create)


async def get_subscription_for_user(
    db: AsyncSession,
    user_id: int,
) -> Optional[PlanSubscription]:
    """Return the active plan subscription for the user, if any."""
    result = await db.execute(
        select(PlanSubscription).where(PlanSubscription.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def require_active_subscription(db: AsyncSession, user_id: int) -> None:
    """
    Ensure the user has an active subscription when billing is configured.
    If billing is not configured, no-op (sync remains available).
    Raises HTTPException 403 if billing is configured and user has no active subscription.
    """
    if not is_billing_configured():
        return
    sub = await get_subscription_for_user(db, user_id)
    if not sub or sub.status != SUBSCRIPTION_STATUS_ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="An active subscription is required to use sync.",
        )


def verify_webhook_signature(
    payload_body: bytes | str,
    headers: dict[str, str],
    secret: str,
) -> bool:
    """
    Verify Standard Webhooks signature.
    Expects headers: webhook-id, webhook-signature, webhook-timestamp.
    """
    webhook_id = headers.get("webhook-id")
    signature = headers.get("webhook-signature")
    timestamp = headers.get("webhook-timestamp")
    if not webhook_id or not signature or not timestamp:
        return False
    if isinstance(payload_body, str):
        payload_body = payload_body.encode("utf-8")
    elif isinstance(payload_body, bytes):
        pass
    else:
        return False

    signed_content = f"{webhook_id}.{timestamp}.".encode("utf-8") + payload_body
    expected = hmac.new(
        secret.encode("utf-8"),
        signed_content,
        hashlib.sha256,
    ).hexdigest()

    # Signature header can be "v1,hexsig" or multiple "v1,sig1 v1,sig2"
    for part in signature.split():
        if "," in part:
            prefix, sig = part.split(",", 1)
            if prefix.strip() == "v1" and hmac.compare_digest(sig.strip(), expected):
                return True
    return False


def is_webhook_duplicate(webhook_id: str) -> bool:
    """Return True if this webhook_id was already processed (idempotency)."""
    return webhook_id in _processed_webhook_ids


def mark_webhook_processed(webhook_id: str) -> None:
    """Mark webhook_id as processed. Evict old entries if cache is too large."""
    global _processed_webhook_ids
    _processed_webhook_ids.add(webhook_id)
    if len(_processed_webhook_ids) > _MAX_CACHED_WEBHOOK_IDS:
        _processed_webhook_ids = set(list(_processed_webhook_ids)[-_MAX_CACHED_WEBHOOK_IDS:])


async def handle_webhook_event(db: AsyncSession, event: dict[str, Any]) -> None:
    """
    Process a verified webhook event: update PlanSubscription by event type.
    Event shape: { "type": "...", "data": { ... }, "business_id", "timestamp" }.
    """
    event_type = event.get("type") or ""
    data = event.get("data") or {}

    if event_type.startswith("subscription."):
        await _handle_subscription_event(db, event_type, data)
    elif event_type in ("payment.succeeded", "payment.failed"):
        await _handle_payment_event(db, event_type, data)
    else:
        logger.debug("Unhandled webhook event type: %s", event_type)


async def _handle_subscription_event(
    db: AsyncSession,
    event_type: str,
    data: dict[str, Any],
) -> None:
    """Create or update PlanSubscription from subscription event data."""
    # Dodo sends subscription object in data (payload_type + subscription fields)
    obj = data
    sub_id = obj.get("id") or obj.get("subscription_id")
    customer_id = obj.get("customer_id") or (obj.get("customer") or {}).get("id") if isinstance(obj.get("customer"), dict) else None
    if not sub_id:
        logger.warning("Subscription event missing subscription id: %s", data)
        return

    status = _map_subscription_status(event_type, obj.get("status"))
    if not customer_id:
        customer_id = obj.get("customer_id", "")

    # Resolve user_id from metadata (set at checkout) or existing row
    user_id = None
    metadata = obj.get("metadata") or {}
    if isinstance(metadata, dict):
        uid = metadata.get("user_id")
        if uid is not None:
            user_id = int(uid) if isinstance(uid, str) else uid

    if user_id is None:
        result = await db.execute(
            select(PlanSubscription).where(
                PlanSubscription.dodo_subscription_id == sub_id
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            user_id = existing.user_id
        else:
            logger.warning("Subscription event has no user_id in metadata and no existing row: %s", sub_id)
            return

    current_period_end = None
    if "current_period_end" in obj:
        raw = obj["current_period_end"]
        if raw:
            from datetime import datetime
            if isinstance(raw, str):
                try:
                    current_period_end = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                except ValueError:
                    pass
            elif hasattr(raw, "isoformat"):
                current_period_end = raw

    result = await db.execute(
        select(PlanSubscription).where(
            PlanSubscription.dodo_subscription_id == sub_id
        )
    )
    row = result.scalar_one_or_none()
    if row:
        row.status = status
        if current_period_end is not None:
            row.current_period_end = current_period_end
        row.dodo_customer_id = customer_id or row.dodo_customer_id
    else:
        row = PlanSubscription(
            user_id=user_id,
            dodo_subscription_id=sub_id,
            dodo_customer_id=customer_id or "",
            status=status,
            current_period_end=current_period_end,
        )
        db.add(row)
    logger.info("Updated PlanSubscription %s for user_id=%s status=%s", sub_id, user_id, status)


def _map_subscription_status(event_type: str, status: Optional[str]) -> str:
    """Map webhook event type and optional status to our status string."""
    if event_type == "subscription.active" or event_type == "subscription.renewed":
        return "active"
    if event_type == "subscription.created":
        return status or "active"
    if event_type == "subscription.updated":
        return status or "active"
    if event_type == "subscription.on_hold":
        return "on_hold"
    if event_type == "subscription.failed":
        return "failed"
    if event_type in ("subscription.canceled", "subscription.cancelled"):
        return "canceled"
    if event_type == "subscription.expired":
        return "expired"
    return status or "unknown"


async def _handle_payment_event(
    db: AsyncSession,
    event_type: str,
    data: dict[str, Any],
) -> None:
    """Optionally update subscription or link payment to subscription."""
    payload_type = data.get("payload_type")
    obj = data
    payment_id = obj.get("id")
    subscription_id = obj.get("subscription_id")
    if not subscription_id:
        return
    result = await db.execute(
        select(PlanSubscription).where(
            PlanSubscription.dodo_subscription_id == subscription_id
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        return
    if event_type == "payment.failed":
        row.status = "past_due"
        logger.info("Marked PlanSubscription %s past_due after payment.failed", subscription_id)
    # payment.succeeded: subscription.renewed or subscription.active usually covers it; no change needed unless you track last_payment_id
