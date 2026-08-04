"""Billing service: Dodo Payments checkout and webhook handling."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Any, Literal, Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models.plan_subscription import PlanSubscription
from models.processed_dodo_webhook import ProcessedDodoWebhook

logger = logging.getLogger(__name__)

SUBSCRIPTION_STATUS_ACTIVE = "active"

# ponytail: in-memory plans cache is single-process only; use shared cache or drop TTL when multi-worker.
_plans_cache: list[dict[str, Any]] | None = None
_plans_cache_time: float = 0.0
_PLANS_CACHE_TTL_SECONDS = 300  # 5 minutes


def _get_dodo_client():
    """Return a configured Dodo Payments client (sync)."""
    from dodopayments import DodoPayments

    env = (settings.DODO_PAYMENTS_ENVIRONMENT or "test").lower()
    environment = "test_mode" if env == "test" else "live_mode"
    return DodoPayments(
        bearer_token=settings.DODO_PAYMENTS_API_KEY,
        environment=environment,
    )


def _get_dodo_webhook_client(webhook_secret: str):
    """Return a Dodo Payments client configured with webhook_key for signature verification (sync)."""
    from dodopayments import DodoPayments

    env = (settings.DODO_PAYMENTS_ENVIRONMENT or "test").lower()
    environment = "test_mode" if env == "test" else "live_mode"
    return DodoPayments(
        bearer_token=settings.DODO_PAYMENTS_API_KEY,
        environment=environment,
        webhook_key=webhook_secret,
    )


def unwrap_webhook(
    body: bytes,
    headers: dict[str, str],
    webhook_secret: str,
) -> dict[str, Any]:
    """
    Verify webhook signature and return the parsed event using Dodo SDK.
    Raises on invalid signature or bad payload.
    """
    client = _get_dodo_webhook_client(webhook_secret)
    payload_str = body.decode("utf-8")
    result = client.webhooks.unwrap(payload_str, headers=headers)
    if hasattr(result, "model_dump"):
        return result.model_dump()
    return dict(result) if result is not None else {}


def unsafe_unwrap_webhook(body: bytes) -> Any:
    """
    Parse webhook payload without signature verification (Dodo SDK unsafe_unwrap).
    Use only for diagnostic logging when verification fails.
    """
    client = _get_dodo_client()
    payload_str = body.decode("utf-8")
    return client.webhooks.unsafe_unwrap(payload_str)


def _webhook_event_log_summary(event: Any) -> dict[str, Any]:
    """Build a minimal, safe dict from a webhook event for logging (no PII)."""
    summary: dict[str, Any] = {}
    if hasattr(event, "type"):
        summary["type"] = event.type
    if hasattr(event, "timestamp"):
        summary["timestamp"] = str(event.timestamp)
    if hasattr(event, "business_id"):
        summary["business_id"] = event.business_id
    if hasattr(event, "data") and event.data is not None:
        if hasattr(event.data, "model_dump"):
            data_keys = list(event.data.model_dump().keys()) if event.data else []
        elif hasattr(event.data, "keys"):
            data_keys = list(event.data.keys())
        else:
            data_keys = []
        summary["data_keys"] = data_keys
    return summary


def is_billing_configured() -> bool:
    """True if Dodo Payments API key and at least one plan product ID are set (sync gating, etc.)."""
    if not settings.DODO_PAYMENTS_API_KEY:
        return False
    return bool(settings.DODO_PAYMENTS_MONTHLY or settings.DODO_PAYMENTS_ANNUAL)


def is_plans_configured() -> bool:
    """True if Dodo Payments API key and at least one plan product ID are set."""
    if not settings.DODO_PAYMENTS_API_KEY:
        return False
    return bool(settings.DODO_PAYMENTS_MONTHLY or settings.DODO_PAYMENTS_ANNUAL)


def get_allowed_product_ids() -> list[str]:
    """Return plan product IDs allowed for checkout (from env). Empty if none configured."""
    ids: list[str] = []
    for pid in (settings.DODO_PAYMENTS_MONTHLY, settings.DODO_PAYMENTS_ANNUAL):
        if pid and pid.strip():
            ids.append(pid.strip())
    return ids


def _price_to_dict(price: Any) -> dict[str, Any]:
    """Serialize Dodo Price (one_time_price, recurring_price, or usage_based_price) to a dict."""
    out: dict[str, Any] = {
        "type": getattr(price, "type", "unknown"),
        "currency": getattr(price, "currency", None),
        "price": getattr(price, "price", None) or getattr(price, "fixed_price", None),
    }
    if hasattr(price, "payment_frequency_interval") and price.payment_frequency_interval is not None:
        out["payment_frequency_interval"] = str(price.payment_frequency_interval)
    if getattr(price, "payment_frequency_count", None) is not None:
        out["payment_frequency_count"] = getattr(price, "payment_frequency_count", None)
    if hasattr(price, "subscription_period_interval") and price.subscription_period_interval is not None:
        out["subscription_period_interval"] = str(price.subscription_period_interval)
    if hasattr(price, "subscription_period_count"):
        out["subscription_period_count"] = getattr(price, "subscription_period_count", None)
    if hasattr(price, "discount"):
        out["discount"] = getattr(price, "discount", None)
    if hasattr(price, "trial_period_days"):
        out["trial_period_days"] = getattr(price, "trial_period_days", None)
    return out


def _addon_to_dict(addon: Any) -> dict[str, Any]:
    """Convert a Dodo Addon instance to a serializable dict for the API."""
    return {
        "id": getattr(addon, "id", ""),
        "name": getattr(addon, "name", None),
        "description": getattr(addon, "description", None),
        "image": getattr(addon, "image", None),
        "price": getattr(addon, "price", None),
        "currency": str(getattr(addon, "currency", "")) if getattr(addon, "currency", None) is not None else None,
        "tax_category": str(getattr(addon, "tax_category", "")),
    }


def _meter_to_dict(meter: Any) -> dict[str, Any]:
    """Convert a Dodo Meter instance to a serializable dict for the API."""
    aggregation = getattr(meter, "aggregation", None)
    agg_dict: dict[str, Any] = {}
    if aggregation is not None:
        agg_dict = {
            "type": getattr(aggregation, "type", None),
            "key": getattr(aggregation, "key", None),
        }
    return {
        "id": getattr(meter, "id", ""),
        "name": getattr(meter, "name", None),
        "description": getattr(meter, "description", None),
        "event_name": getattr(meter, "event_name", None),
        "aggregation": agg_dict,
        "measurement_unit": getattr(meter, "measurement_unit", None),
    }


def _product_to_plan_dict(product: Any) -> dict[str, Any]:
    """Convert a Dodo Product instance to a serializable plan dict for the API."""
    price = getattr(product, "price", None)
    return {
        "product_id": getattr(product, "product_id", ""),
        "name": getattr(product, "name", None),
        "description": getattr(product, "description", None),
        "image": getattr(product, "image", None),
        "is_recurring": getattr(product, "is_recurring", False),
        "price": _price_to_dict(price) if price else {},
        "metadata": dict(getattr(product, "metadata", None) or {}),
        "tax_category": str(getattr(product, "tax_category", "")),
        "addons": [],
        "meters": [],
    }


PlanTypeLiteral = Literal["monthly", "annual"]


def _get_plan_slots() -> list[tuple[PlanTypeLiteral, str]]:
    """Return (plan_type, product_id) for each configured slot."""
    slots: list[tuple[PlanTypeLiteral, str]] = []
    for plan_type, pid in [
        ("monthly", settings.DODO_PAYMENTS_MONTHLY),
        ("annual", settings.DODO_PAYMENTS_ANNUAL),
    ]:
        if pid and pid.strip():
            slots.append((plan_type, pid.strip()))
    return slots


def _fetch_plans_from_dodo() -> list[dict[str, Any]]:
    """
    Fetch env-configured plans from Dodo by product ID.
    Returns plans in fixed order. Each plan has plan_type and show_discounted_badge (annual only).
    Sync, runs in thread.
    """
    client = _get_dodo_client()
    plans: list[dict[str, Any]] = []

    for plan_type, product_id in _get_plan_slots():
        try:
            product = client.products.retrieve(product_id)
        except Exception as e:
            logger.warning("Failed to retrieve product %s: %s", product_id, e)
            continue
        plan = _product_to_plan_dict(product)
        plan["plan_type"] = plan_type
        plan["show_discounted_badge"] = plan_type == "annual"
        addon_ids = getattr(product, "addons", None) or []
        for addon_id in addon_ids:
            if not addon_id:
                continue
            try:
                addon = client.addons.retrieve(addon_id)
                plan["addons"].append(_addon_to_dict(addon))
            except Exception as e:
                logger.warning("Failed to retrieve addon %s: %s", addon_id, e)
        price = getattr(product, "price", None)
        meter_ids: list[str] = []
        if price is not None and getattr(price, "type", None) == "usage_based_price":
            meters_attr = getattr(price, "meters", None) or []
            for m in meters_attr:
                mid = getattr(m, "meter_id", None)
                if mid:
                    meter_ids.append(mid)
        for meter_id in meter_ids:
            try:
                meter = client.meters.retrieve(meter_id)
                plan["meters"].append(_meter_to_dict(meter))
            except Exception as e:
                logger.warning("Failed to retrieve meter %s: %s", meter_id, e)
        plans.append(plan)

    return plans


async def get_plans() -> list[dict[str, Any]]:
    """
    Return available plan details (from Dodo Payments), served from in-memory cache when valid.
    Returns empty list if plans are not configured (API key missing). Logs full plan details for debugging.
    """
    global _plans_cache, _plans_cache_time

    if not is_plans_configured():
        return []

    now = time.monotonic()
    if _plans_cache is not None and (now - _plans_cache_time) < _PLANS_CACHE_TTL_SECONDS:
        return _plans_cache

    try:
        plans = await asyncio.to_thread(_fetch_plans_from_dodo)
    except Exception as e:
        logger.exception("Failed to fetch plans from Dodo: %s", e)
        raise

    _plans_cache = plans
    _plans_cache_time = now

    try:
        plans_json = json.dumps(plans, default=str)
    except (TypeError, ValueError):
        plans_json = str(plans)
    logger.debug("Plans loaded: %s", plans_json)

    return plans


async def create_checkout_session(
    user_id: int,
    product_id: str,
    return_url: Optional[str] = None,
    customer_email: Optional[str] = None,
    customer_name: Optional[str] = None,
) -> dict[str, str]:
    """
    Create a Dodo Checkout Session for the given plan product.
    Checkout is single-product only; no addons or separate usage product.
    """
    if not is_plans_configured():
        raise ValueError("Dodo Payments is not configured")
    allowed = get_allowed_product_ids()
    if not allowed:
        raise ValueError("No plan products configured for checkout")
    if product_id not in allowed:
        raise ValueError("product_id is not an allowed plan")

    def _create() -> dict[str, str]:
        client = _get_dodo_client()
        product_cart: list[dict[str, Any]] = [
            {"product_id": product_id, "quantity": 1},
        ]
        payload: dict[str, Any] = {
            "product_cart": product_cart,
            "metadata": {"user_id": str(user_id)},
        }
        customer: dict[str, str] = {}
        if customer_email and customer_email.strip():
            customer["email"] = customer_email.strip()
        if customer_name and customer_name.strip():
            customer["name"] = customer_name.strip()
        if customer:
            payload["customer"] = customer
        if return_url:
            payload["return_url"] = return_url
        resp = client.checkout_sessions.create(**payload)
        return {
            "session_id": resp.session_id,
            "checkout_url": resp.checkout_url or "",
        }

    return await asyncio.to_thread(_create)


async def create_customer_portal_session(customer_id: str) -> dict[str, str]:
    """Create a Dodo customer portal session link for self-service subscription management."""
    if not is_plans_configured():
        raise ValueError("Dodo Payments is not configured")
    cid = (customer_id or "").strip()
    if not cid:
        raise ValueError("customer_id is required")

    def _create() -> dict[str, str]:
        client = _get_dodo_client()
        resp = client.customers.customer_portal.create(cid)
        return {"portal_url": resp.link or ""}

    return await asyncio.to_thread(_create)


class BillingCompleteError(Exception):
    """Raised by complete_subscription with (status_code, detail)."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def _parse_period_end(raw: Any) -> Optional[datetime]:
    """Parse Dodo next_billing_date or current_period_end into a datetime."""
    if not raw:
        return None
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    if hasattr(raw, "isoformat"):
        return raw
    return None


def _period_end_from_obj(obj: dict[str, Any]) -> Optional[datetime]:
    """Extract period end from a subscription payload (webhook or API-shaped dict)."""
    for key in ("next_billing_date", "current_period_end"):
        if key in obj and obj[key]:
            parsed = _parse_period_end(obj[key])
            if parsed is not None:
                return parsed
    return None


def _extract_product_id(obj: dict[str, Any]) -> Optional[str]:
    raw_pid = obj.get("product_id")
    if raw_pid and isinstance(raw_pid, str):
        product_id = raw_pid.strip()
        if product_id:
            return product_id
    items = obj.get("items")
    if items and len(items) > 0:
        first = items[0]
        if isinstance(first, dict):
            raw_pid = first.get("product_id") or first.get("product")
            if raw_pid and isinstance(raw_pid, str):
                product_id = raw_pid.strip()
                if product_id:
                    return product_id
    return None


async def _upsert_plan_subscription(
    db: AsyncSession,
    *,
    user_id: int,
    dodo_subscription_id: str,
    dodo_customer_id: str,
    status: str,
    product_id: Optional[str] = None,
    current_period_end: Optional[datetime] = None,
) -> PlanSubscription:
    """
    Insert or update the user's PlanSubscription row.
    Looks up by dodo_subscription_id first, then by user_id (re-subscription).
    """
    result = await db.execute(
        select(PlanSubscription).where(
            PlanSubscription.dodo_subscription_id == dodo_subscription_id
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        result = await db.execute(
            select(PlanSubscription).where(PlanSubscription.user_id == user_id)
        )
        row = result.scalar_one_or_none()

    if row:
        row.user_id = user_id
        row.dodo_subscription_id = dodo_subscription_id
        row.status = status
        if current_period_end is not None:
            row.current_period_end = current_period_end
        if dodo_customer_id:
            row.dodo_customer_id = dodo_customer_id
        if product_id is not None:
            row.product_id = product_id
        return row

    row = PlanSubscription(
        user_id=user_id,
        dodo_subscription_id=dodo_subscription_id,
        dodo_customer_id=dodo_customer_id or "",
        status=status,
        product_id=product_id,
        current_period_end=current_period_end,
    )
    db.add(row)
    return row


async def complete_subscription(
    db: AsyncSession,
    user_id: int,
    subscription_id: str,
    status: str,
) -> None:
    """
    Verify subscription with Dodo, ensure it belongs to the current user, and upsert PlanSubscription.
    Raises BillingCompleteError with (status_code, detail) for 400, 403, 404, 502.
    """
    if not is_plans_configured():
        raise BillingCompleteError(503, "Billing is not configured")
    if not subscription_id or not subscription_id.strip():
        raise BillingCompleteError(400, "subscription_id is required and cannot be empty")
    if not status or not status.strip():
        raise BillingCompleteError(400, "status is required and cannot be empty")
    subscription_id = subscription_id.strip()
    status = status.strip()

    def _retrieve() -> Any:
        client = _get_dodo_client()
        return client.subscriptions.retrieve(subscription_id)

    try:
        sub = await asyncio.to_thread(_retrieve)
    except Exception as e:
        err_module = getattr(e, "__class__", None).__module__
        err_name = type(e).__name__
        if err_module and "dodopayments" in err_module and err_name == "NotFoundError":
            raise BillingCompleteError(404, "Subscription not found") from e
        logger.exception("Dodo API error retrieving subscription %s: %s", subscription_id, e)
        raise BillingCompleteError(502, "Failed to verify subscription with payment provider") from e

    dodo_status = getattr(sub, "status", None) or getattr(sub, "subscription_status", None)
    if not dodo_status:
        dodo_status = ""
    dodo_status_str = str(dodo_status).strip()
    if dodo_status_str.lower() != status.strip().lower():
        raise BillingCompleteError(
            400,
            "Subscription status does not match",
        )

    metadata = getattr(sub, "metadata", None) or {}
    if isinstance(metadata, dict):
        meta_user_id = metadata.get("user_id")
    else:
        meta_user_id = None
    if meta_user_id is not None:
        meta_user_id = str(meta_user_id).strip()
    if meta_user_id != str(user_id):
        raise BillingCompleteError(
            403,
            "Subscription does not belong to this user",
        )

    customer_id = ""
    if hasattr(sub, "customer") and sub.customer is not None:
        c = sub.customer
        customer_id = getattr(c, "customer_id", None) or getattr(c, "id", None) or ""
    if hasattr(sub, "customer_id") and sub.customer_id:
        customer_id = str(sub.customer_id)
    customer_id = (customer_id or "").strip()

    product_id = None
    if hasattr(sub, "product_id") and sub.product_id:
        product_id = str(sub.product_id).strip() or None

    current_period_end = _period_end_from_obj(
        {"next_billing_date": getattr(sub, "next_billing_date", None)}
    )

    await _upsert_plan_subscription(
        db,
        user_id=user_id,
        dodo_subscription_id=subscription_id,
        dodo_customer_id=customer_id,
        status=dodo_status_str,
        product_id=product_id,
        current_period_end=current_period_end,
    )
    logger.info("Completed subscription %s for user_id=%s status=%s", subscription_id, user_id, dodo_status_str)
    from service.admin_webhook import (
        emit_admin_event,
        subscription_admin_event_from_status,
    )

    admin_event = subscription_admin_event_from_status(dodo_status_str)
    if admin_event:
        await emit_admin_event(
            db,
            admin_event,
            {
                "user_id": user_id,
                "dodo_subscription_id": subscription_id,
                "status": dodo_status_str,
                "product_id": product_id,
            },
        )


async def get_subscription_for_user(
    db: AsyncSession,
    user_id: int,
) -> Optional[PlanSubscription]:
    """Return the active plan subscription for the user, if any."""
    result = await db.execute(
        select(PlanSubscription).where(PlanSubscription.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def try_claim_dodo_webhook_id(db: AsyncSession, webhook_id: str) -> bool:
    """
    Insert webhook_id in a savepoint so only one worker processes a delivery.
    Returns False if this id was already committed (duplicate delivery). True to proceed.
    Blank webhook_id returns True (cannot dedupe; Dodo should always send webhook-id).
    """
    wid = (webhook_id or "").strip()
    if not wid:
        return True
    try:
        async with db.begin_nested():
            db.add(ProcessedDodoWebhook(webhook_id=wid))
            await db.flush()
    except IntegrityError:
        logger.debug("Duplicate Dodo webhook_id (skip): %s", wid[:120])
        return False
    return True


async def handle_webhook_event(db: AsyncSession, event: dict[str, Any]) -> None:
    """
    Process a verified webhook event: update PlanSubscription by event type.
    Event shape: { "type": "...", "data": { ... }, "business_id", "timestamp" }.
    """
    event_type = event.get("type") or ""
    data = event.get("data") or {}

    if event_type.startswith("subscription."):
        await _handle_subscription_event(db, event_type, data)
    else:
        logger.debug("Unhandled webhook event type: %s", event_type)


async def _handle_subscription_event(
    db: AsyncSession,
    event_type: str,
    data: dict[str, Any],
) -> None:
    """Create or update PlanSubscription from subscription event data."""
    obj = data
    sub_id = obj.get("id") or obj.get("subscription_id")
    customer_id = obj.get("customer_id") or (obj.get("customer") or {}).get("id") if isinstance(obj.get("customer"), dict) else None
    if not sub_id:
        logger.warning("Subscription event missing subscription id: %s", data)
        return

    status = _map_subscription_status(event_type, obj.get("status"))
    if not customer_id:
        customer_id = obj.get("customer_id", "")

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

    current_period_end = _period_end_from_obj(obj)

    product_id = _extract_product_id(obj)
    if product_id is None and obj.get("items"):
        logger.debug("Subscription %s webhook has no product_id in common paths", sub_id)

    await _upsert_plan_subscription(
        db,
        user_id=user_id,
        dodo_subscription_id=sub_id,
        dodo_customer_id=customer_id or "",
        status=status,
        product_id=product_id,
        current_period_end=current_period_end,
    )
    logger.info("Updated PlanSubscription %s for user_id=%s status=%s", sub_id, user_id, status)
    from service.admin_webhook import (
        emit_admin_event,
        subscription_admin_event_from_dodo,
        subscription_admin_event_from_status,
    )

    admin_event = subscription_admin_event_from_dodo(event_type)
    if admin_event is None and event_type == "subscription.updated":
        admin_event = subscription_admin_event_from_status(status)
    if admin_event:
        await emit_admin_event(
            db,
            admin_event,
            {
                "user_id": user_id,
                "dodo_subscription_id": sub_id,
                "status": status,
                "product_id": product_id,
                "dodo_event_type": event_type,
            },
        )


def _map_subscription_status(event_type: str, status: Optional[str]) -> str:
    """Map webhook event type and optional status to Dodo's canonical status string."""
    if event_type in ("subscription.active", "subscription.renewed"):
        return "active"
    if event_type == "subscription.on_hold":
        return "on_hold"
    if event_type == "subscription.failed":
        return "failed"
    if event_type in ("subscription.canceled", "subscription.cancelled"):
        return "cancelled"
    if event_type == "subscription.expired":
        return "expired"
    if event_type in ("subscription.updated", "subscription.plan_changed"):
        return (status or "active").strip()
    if status:
        return str(status).strip()
    return "unknown"
