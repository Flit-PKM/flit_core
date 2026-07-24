"""Outbound admin webhooks: emit, deliver, and CRUD for superuser monitoring."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from exceptions import NotFoundError, ValidationError
from logging_config import get_logger
from models.admin_webhook import AdminWebhook

logger = get_logger(__name__)

SESSION_PENDING_KEY = "admin_webhook_events"

# Catalog of event types (production + manual test).
EVENT_USER_SIGNUP = "user.signup"
EVENT_SUBSCRIPTION_ACTIVE = "subscription.active"
EVENT_SUBSCRIPTION_RENEWED = "subscription.renewed"
EVENT_SUBSCRIPTION_ON_HOLD = "subscription.on_hold"
EVENT_SUBSCRIPTION_FAILED = "subscription.failed"
EVENT_SUBSCRIPTION_CANCELLED = "subscription.cancelled"
EVENT_SUBSCRIPTION_EXPIRED = "subscription.expired"
EVENT_SUBSCRIPTION_PLAN_CHANGED = "subscription.plan_changed"
EVENT_FEEDBACK_CREATED = "feedback.created"
EVENT_ACCESS_CODE_ACTIVATED = "access_code.activated"
EVENT_ERROR_UNHANDLED = "error.unhandled"
EVENT_WEBHOOK_TEST = "webhook.test"

ADMIN_EVENT_TYPES: frozenset[str] = frozenset(
    {
        EVENT_USER_SIGNUP,
        EVENT_SUBSCRIPTION_ACTIVE,
        EVENT_SUBSCRIPTION_RENEWED,
        EVENT_SUBSCRIPTION_ON_HOLD,
        EVENT_SUBSCRIPTION_FAILED,
        EVENT_SUBSCRIPTION_CANCELLED,
        EVENT_SUBSCRIPTION_EXPIRED,
        EVENT_SUBSCRIPTION_PLAN_CHANGED,
        EVENT_FEEDBACK_CREATED,
        EVENT_ACCESS_CODE_ACTIVATED,
        EVENT_ERROR_UNHANDLED,
        EVENT_WEBHOOK_TEST,
    }
)

# Dodo inbound types that map 1:1 (or via alias) onto our catalog.
_DODO_TO_ADMIN_SUBSCRIPTION: dict[str, str] = {
    "subscription.active": EVENT_SUBSCRIPTION_ACTIVE,
    "subscription.renewed": EVENT_SUBSCRIPTION_RENEWED,
    "subscription.on_hold": EVENT_SUBSCRIPTION_ON_HOLD,
    "subscription.failed": EVENT_SUBSCRIPTION_FAILED,
    "subscription.canceled": EVENT_SUBSCRIPTION_CANCELLED,
    "subscription.cancelled": EVENT_SUBSCRIPTION_CANCELLED,
    "subscription.expired": EVENT_SUBSCRIPTION_EXPIRED,
    "subscription.plan_changed": EVENT_SUBSCRIPTION_PLAN_CHANGED,
}

_STATUS_TO_ADMIN_SUBSCRIPTION: dict[str, str] = {
    "active": EVENT_SUBSCRIPTION_ACTIVE,
    "on_hold": EVENT_SUBSCRIPTION_ON_HOLD,
    "failed": EVENT_SUBSCRIPTION_FAILED,
    "cancelled": EVENT_SUBSCRIPTION_CANCELLED,
    "canceled": EVENT_SUBSCRIPTION_CANCELLED,
    "expired": EVENT_SUBSCRIPTION_EXPIRED,
}

DELIVERY_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class WebhookDestination:
    """Snapshot of an endpoint for fire-and-forget delivery (no ORM)."""

    id: int
    url: str
    secret: Optional[str]


@dataclass
class PendingAdminWebhook:
    event_type: str
    envelope: dict[str, Any]
    destinations: list[WebhookDestination] = field(default_factory=list)


@dataclass
class DeliveryResult:
    ok: bool
    event_type: str
    status_code: Optional[int]
    latency_ms: int
    error: Optional[str]


def validate_event_types(events: list[str]) -> list[str]:
    if not events:
        raise ValidationError("events must include at least one event type")
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in events:
        et = (raw or "").strip()
        if not et:
            raise ValidationError("events cannot contain empty strings")
        if et not in ADMIN_EVENT_TYPES:
            raise ValidationError(f"Unknown event type: {et}")
        if et not in seen:
            seen.add(et)
            cleaned.append(et)
    return cleaned


def validate_webhook_url(url: str) -> str:
    u = (url or "").strip()
    if not u:
        raise ValidationError("url is required")
    parsed = urlparse(u)
    if parsed.scheme not in ("http", "https"):
        raise ValidationError("url must use http or https")
    if not parsed.netloc:
        raise ValidationError("url must include a host")
    if settings.ENVIRONMENT == "production" and parsed.scheme != "https":
        raise ValidationError("url must use https in production")
    return u


def build_envelope(event_type: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "type": event_type,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "data": data,
    }


def sign_body(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def build_sample_payload(event_type: str) -> dict[str, Any]:
    """Fixed sample data for test fires."""
    if event_type == EVENT_WEBHOOK_TEST:
        return {"message": "Test event from Flit"}
    if event_type == EVENT_USER_SIGNUP:
        return {
            "user_id": 1,
            "email": "sample@example.com",
            "username": "sampleuser",
        }
    if event_type.startswith("subscription."):
        return {
            "user_id": 1,
            "dodo_subscription_id": "sub_sample_123",
            "status": event_type.split(".", 1)[1],
            "product_id": "prod_sample",
        }
    if event_type == EVENT_FEEDBACK_CREATED:
        return {"feedback_id": 1, "content_preview": "Sample feedback…"}
    if event_type == EVENT_ACCESS_CODE_ACTIVATED:
        return {
            "user_id": 1,
            "access_code_id": 1,
            "period_weeks": 4,
        }
    if event_type == EVENT_ERROR_UNHANDLED:
        return {
            "method": "GET",
            "path": "/api/example",
            "exception_type": "RuntimeError",
            "request_id": "00000000-0000-0000-0000-000000000000",
        }
    return {"message": f"Sample payload for {event_type}"}


def subscription_admin_event_from_dodo(event_type: str) -> Optional[str]:
    """Map a Dodo subscription.* type to our catalog, or None if unmapped."""
    return _DODO_TO_ADMIN_SUBSCRIPTION.get(event_type)


def subscription_admin_event_from_status(status: str) -> Optional[str]:
    key = (status or "").strip().lower()
    return _STATUS_TO_ADMIN_SUBSCRIPTION.get(key)


def mask_secret(secret: Optional[str]) -> tuple[bool, Optional[str]]:
    """Return (secret_set, secret_last4)."""
    if not secret:
        return False, None
    last4 = secret[-4:] if len(secret) >= 4 else secret
    return True, last4


def webhook_to_read_dict(row: AdminWebhook) -> dict[str, Any]:
    secret_set, secret_last4 = mask_secret(row.secret)
    return {
        "id": row.id,
        "name": row.name,
        "url": row.url,
        "events": list(row.events or []),
        "enabled": bool(row.enabled),
        "secret_set": secret_set,
        "secret_last4": secret_last4,
        "created_by": row.created_by,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


async def list_webhooks(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 100,
) -> list[AdminWebhook]:
    result = await db.execute(
        select(AdminWebhook)
        .order_by(AdminWebhook.id.asc())
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_webhook(db: AsyncSession, webhook_id: int) -> AdminWebhook:
    result = await db.execute(
        select(AdminWebhook).where(AdminWebhook.id == webhook_id)
    )
    row = result.scalar_one_or_none()
    if not row:
        raise NotFoundError("Webhook not found")
    return row


async def create_webhook(
    db: AsyncSession,
    *,
    name: str,
    url: str,
    events: list[str],
    secret: Optional[str] = None,
    enabled: bool = True,
    created_by: Optional[int] = None,
) -> AdminWebhook:
    validated_url = validate_webhook_url(url)
    validated_events = validate_event_types(events)
    row = AdminWebhook(
        name=name.strip(),
        url=validated_url,
        secret=(secret.strip() if secret and secret.strip() else None),
        events=validated_events,
        enabled=enabled,
        created_by=created_by,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    logger.info("Admin webhook created id=%s name=%s", row.id, row.name)
    return row


async def update_webhook(
    db: AsyncSession,
    webhook_id: int,
    *,
    name: Optional[str] = None,
    url: Optional[str] = None,
    events: Optional[list[str]] = None,
    secret: Optional[str] = None,
    clear_secret: bool = False,
    enabled: Optional[bool] = None,
) -> AdminWebhook:
    row = await get_webhook(db, webhook_id)
    if name is not None:
        row.name = name.strip()
    if url is not None:
        row.url = validate_webhook_url(url)
    if events is not None:
        row.events = validate_event_types(events)
    if clear_secret:
        row.secret = None
    elif secret is not None:
        row.secret = secret.strip() if secret.strip() else None
    if enabled is not None:
        row.enabled = enabled
    await db.flush()
    await db.refresh(row)
    return row


async def delete_webhook(db: AsyncSession, webhook_id: int) -> None:
    row = await get_webhook(db, webhook_id)
    await db.delete(row)
    await db.flush()
    logger.info("Admin webhook deleted id=%s", webhook_id)


async def _load_matching_destinations(
    db: AsyncSession,
    event_type: str,
) -> list[WebhookDestination]:
    result = await db.execute(
        select(AdminWebhook).where(AdminWebhook.enabled.is_(True))
    )
    rows = result.scalars().all()
    dests: list[WebhookDestination] = []
    for row in rows:
        subscribed = row.events or []
        if event_type in subscribed:
            dests.append(
                WebhookDestination(id=row.id, url=row.url, secret=row.secret)
            )
    return dests


async def emit_admin_event(
    session: AsyncSession,
    event_type: str,
    data: dict[str, Any],
) -> None:
    """
    Queue an admin event for post-commit fire-and-forget delivery.
    Snapshots matching destinations now so delivery needs no DB.
    """
    if event_type not in ADMIN_EVENT_TYPES or event_type == EVENT_WEBHOOK_TEST:
        if event_type != EVENT_WEBHOOK_TEST:
            logger.warning("Ignoring unknown admin event type: %s", event_type)
        return
    try:
        destinations = await _load_matching_destinations(session, event_type)
    except Exception:
        logger.exception("Failed to load admin webhook destinations for %s", event_type)
        return
    if not destinations:
        return
    envelope = build_envelope(event_type, data)
    pending: list[PendingAdminWebhook] = session.info.setdefault(
        SESSION_PENDING_KEY, []
    )
    pending.append(
        PendingAdminWebhook(
            event_type=event_type,
            envelope=envelope,
            destinations=destinations,
        )
    )


async def deliver_to_endpoint(
    destination: WebhookDestination,
    envelope: dict[str, Any],
) -> DeliveryResult:
    event_type = str(envelope.get("type") or "")
    body = json.dumps(envelope, separators=(",", ":"), default=str).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "X-Flit-Event": event_type,
        "User-Agent": "Flit-Admin-Webhook/1.0",
    }
    if destination.secret:
        headers["X-Flit-Signature"] = sign_body(destination.secret, body)

    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=DELIVERY_TIMEOUT_SECONDS) as client:
            response = await client.post(
                destination.url,
                content=body,
                headers=headers,
            )
        latency_ms = int((time.perf_counter() - started) * 1000)
        ok = 200 <= response.status_code < 300
        if not ok:
            logger.warning(
                "Admin webhook delivery non-2xx webhook_id=%s status=%s event=%s",
                destination.id,
                response.status_code,
                event_type,
            )
        return DeliveryResult(
            ok=ok,
            event_type=event_type,
            status_code=response.status_code,
            latency_ms=latency_ms,
            error=None if ok else f"HTTP {response.status_code}",
        )
    except Exception as e:
        latency_ms = int((time.perf_counter() - started) * 1000)
        logger.exception(
            "Admin webhook delivery failed webhook_id=%s event=%s: %s",
            destination.id,
            event_type,
            e,
        )
        return DeliveryResult(
            ok=False,
            event_type=event_type,
            status_code=None,
            latency_ms=latency_ms,
            error=str(e) or type(e).__name__,
        )


async def dispatch_pending_admin_webhooks(
    pending: list[PendingAdminWebhook],
) -> None:
    """Deliver all queued events; never raises."""
    try:
        for item in pending:
            for dest in item.destinations:
                await deliver_to_endpoint(dest, item.envelope)
    except Exception:
        logger.exception("Unexpected error dispatching admin webhooks")


def schedule_pending_admin_webhooks(pending: list[PendingAdminWebhook]) -> None:
    """Fire-and-forget after commit (production path)."""
    if not pending:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("No running loop; dropping %s admin webhook event(s)", len(pending))
        return
    loop.create_task(dispatch_pending_admin_webhooks(pending))


async def emit_error_unhandled_best_effort(
    *,
    method: str,
    path: str,
    exception_type: str,
    request_id: Optional[str] = None,
) -> None:
    """
    Load matching endpoints with a fresh session and deliver immediately.
    Used when there is no request DB session (middleware / exception handlers).
    """
    from database.engine import AsyncSessionFactory

    data = {
        "method": method,
        "path": path,
        "exception_type": exception_type,
        "request_id": request_id,
    }
    try:
        async with AsyncSessionFactory() as session:
            destinations = await _load_matching_destinations(
                session, EVENT_ERROR_UNHANDLED
            )
        if not destinations:
            return
        envelope = build_envelope(EVENT_ERROR_UNHANDLED, data)
        pending = [
            PendingAdminWebhook(
                event_type=EVENT_ERROR_UNHANDLED,
                envelope=envelope,
                destinations=destinations,
            )
        ]
        schedule_pending_admin_webhooks(pending)
    except Exception:
        logger.exception("Failed to emit error.unhandled admin webhook")


async def fire_test_event(
    db: AsyncSession,
    webhook_id: int,
    event_type: Optional[str] = None,
) -> DeliveryResult:
    """
    Synchronously POST a test (or sample catalog) event to one endpoint.
    Ignores enabled flag and event filters.
    """
    row = await get_webhook(db, webhook_id)
    et = (event_type or EVENT_WEBHOOK_TEST).strip() or EVENT_WEBHOOK_TEST
    if et not in ADMIN_EVENT_TYPES:
        raise ValidationError(f"Unknown event type: {et}")
    data = build_sample_payload(et)
    envelope = build_envelope(et, data)
    dest = WebhookDestination(id=row.id, url=row.url, secret=row.secret)
    return await deliver_to_endpoint(dest, envelope)
