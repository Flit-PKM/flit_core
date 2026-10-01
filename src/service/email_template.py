"""Resolve, render, and send admin-editable user email templates."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import NotFoundError
from logging_config import get_logger
from models.email_template import EmailTemplate
from service.email import send_email

logger = get_logger(__name__)

_PLACEHOLDER_RE = re.compile(r"\{([a-z_]+)\}")


@dataclass(frozen=True)
class TemplateSpec:
    description: str
    placeholders: tuple[str, ...]
    default_enabled: bool
    default_subject: str
    default_body_text: str
    default_body_html: str


CATALOG: dict[str, TemplateSpec] = {
    "welcome": TemplateSpec(
        description="Sent once when a user row is created (password, Google, MCP, admin).",
        placeholders=("username", "email"),
        default_enabled=True,
        default_subject="Welcome to Flit",
        default_body_text=(
            "Hi {username},\n\n"
            "Thanks for creating a Flit account ({email}).\n\n"
            "— Flit"
        ),
        default_body_html=(
            "<p>Hi {username},</p>\n"
            "<p>Thanks for creating a Flit account ({email}).</p>\n"
            "<p>— Flit</p>"
        ),
    ),
    "email_verify": TemplateSpec(
        description="Email verification link. Password register auto-sends; GET /api/verify resends.",
        placeholders=("username", "email", "link", "expire_hours"),
        default_enabled=True,
        default_subject="Verify your Flit email address",
        default_body_text=(
            "Hi {username},\n\n"
            "Please verify your email address by clicking the link below:\n\n"
            "{link}\n\n"
            "This link expires in {expire_hours} hours.\n\n"
            "If you did not request this, you can ignore this email.\n\n"
            "— Flit"
        ),
        default_body_html=(
            "<p>Hi {username},</p>\n"
            "<p>Please verify your email address by clicking the link below:</p>\n"
            '<p><a href="{link}">{link}</a></p>\n'
            "<p>This link expires in {expire_hours} hours.</p>\n"
            "<p>If you did not request this, you can ignore this email.</p>\n"
            "<p>— Flit</p>"
        ),
    ),
    "password_reset": TemplateSpec(
        description="Password reset link. Skips unknown and unverified addresses (no enumeration).",
        placeholders=("username", "email", "link", "expire_hours"),
        default_enabled=True,
        default_subject="Reset your Flit password",
        default_body_text=(
            "Hi {username},\n\n"
            "We received a request to reset your password. Click the link below to set a new one:\n\n"
            "{link}\n\n"
            "This link expires in {expire_hours} hour(s).\n\n"
            "If you did not request this, you can ignore this email. Your password will not change.\n\n"
            "— Flit"
        ),
        default_body_html=(
            "<p>Hi {username},</p>\n"
            "<p>We received a request to reset your password. Click the link below to set a new one:</p>\n"
            '<p><a href="{link}">{link}</a></p>\n'
            "<p>This link expires in {expire_hours} hour(s).</p>\n"
            "<p>If you did not request this, you can ignore this email. Your password will not change.</p>\n"
            "<p>— Flit</p>"
        ),
    ),
    "mailing_list_confirm": TemplateSpec(
        description="Confirmation after a successful public mailing-list subscribe.",
        placeholders=("email",),
        default_enabled=True,
        default_subject="You're subscribed to the Flit mailing list",
        default_body_text=(
            "You're subscribed to the Flit mailing list ({email}).\n\n"
            "— Flit"
        ),
        default_body_html=(
            "<p>You're subscribed to the Flit mailing list ({email}).</p>\n"
            "<p>— Flit</p>"
        ),
    ),
}

_BILLING_KEYS = (
    "subscription.active",
    "subscription.renewed",
    "subscription.on_hold",
    "subscription.failed",
    "subscription.cancelled",
    "subscription.expired",
    "subscription.plan_changed",
)

_BILLING_DESCRIPTIONS = {
    "subscription.active": "Plan subscription became active (Dodo webhook only).",
    "subscription.renewed": "Plan subscription renewed (Dodo webhook only).",
    "subscription.on_hold": "Plan subscription on hold (Dodo webhook only).",
    "subscription.failed": "Plan subscription payment failed (Dodo webhook only).",
    "subscription.cancelled": "Plan subscription cancelled (Dodo webhook only).",
    "subscription.expired": "Plan subscription expired (Dodo webhook only).",
    "subscription.plan_changed": "Plan subscription product/plan changed (Dodo webhook only).",
}

for _key in _BILLING_KEYS:
    CATALOG[_key] = TemplateSpec(
        description=_BILLING_DESCRIPTIONS[_key],
        placeholders=("username", "email", "status", "product_id"),
        default_enabled=False,
        default_subject="Your Flit subscription update",
        default_body_text=(
            "Hi {username},\n\n"
            "Your Flit subscription is now {status}.\n"
            "Product: {product_id}\n\n"
            "— Flit"
        ),
        default_body_html=(
            "<p>Hi {username},</p>\n"
            "<p>Your Flit subscription is now {status}.</p>\n"
            "<p>Product: {product_id}</p>\n"
            "<p>— Flit</p>"
        ),
    )


def render(template: str, values: dict[str, str]) -> str:
    """Replace {name} for keys present in values; leave unknown {foo} intact."""

    def _repl(match: re.Match[str]) -> str:
        name = match.group(1)
        if name in values:
            return str(values[name])
        return match.group(0)

    return _PLACEHOLDER_RE.sub(_repl, template)


def sample_values(key: str, email: str) -> dict[str, str]:
    spec = CATALOG.get(key)
    if spec is None:
        return {"email": email}
    values = {
        "username": "Ada",
        "email": email,
        "link": "https://example.com/link",
        "expire_hours": "24",
        "status": "active",
        "product_id": "prod_sample",
    }
    return {k: values[k] for k in spec.placeholders}


@dataclass
class ResolvedTemplate:
    key: str
    description: str
    placeholders: tuple[str, ...]
    subject: str
    body_text: str
    body_html: Optional[str]
    enabled: bool
    is_overridden: bool


async def _row_for_key(db: AsyncSession, key: str) -> Optional[EmailTemplate]:
    result = await db.execute(select(EmailTemplate).where(EmailTemplate.key == key))
    return result.scalar_one_or_none()


async def resolve(db: AsyncSession, key: str) -> ResolvedTemplate:
    spec = CATALOG.get(key)
    if spec is None:
        raise NotFoundError(f"Unknown email template: {key}")
    row = await _row_for_key(db, key)
    if row is None:
        return ResolvedTemplate(
            key=key,
            description=spec.description,
            placeholders=spec.placeholders,
            subject=spec.default_subject,
            body_text=spec.default_body_text,
            body_html=spec.default_body_html,
            enabled=spec.default_enabled,
            is_overridden=False,
        )
    return ResolvedTemplate(
        key=key,
        description=spec.description,
        placeholders=spec.placeholders,
        subject=row.subject,
        body_text=row.body_text,
        body_html=row.body_html,
        enabled=row.enabled,
        is_overridden=True,
    )


async def list_templates(db: AsyncSession) -> list[ResolvedTemplate]:
    return [await resolve(db, key) for key in CATALOG]


async def upsert_template(
    db: AsyncSession,
    key: str,
    *,
    subject: Optional[str] = None,
    body_text: Optional[str] = None,
    body_html: Optional[str] = None,
    enabled: Optional[bool] = None,
) -> ResolvedTemplate:
    spec = CATALOG.get(key)
    if spec is None:
        raise NotFoundError(f"Unknown email template: {key}")
    row = await _row_for_key(db, key)
    if row is None:
        row = EmailTemplate(
            key=key,
            subject=spec.default_subject,
            body_text=spec.default_body_text,
            body_html=spec.default_body_html,
            enabled=spec.default_enabled,
        )
        db.add(row)
    if subject is not None:
        row.subject = subject
    if body_text is not None:
        row.body_text = body_text
    if body_html is not None:
        row.body_html = body_html
    if enabled is not None:
        row.enabled = enabled
    await db.flush()
    await db.refresh(row)
    return await resolve(db, key)


async def reset_template(db: AsyncSession, key: str) -> ResolvedTemplate:
    if key not in CATALOG:
        raise NotFoundError(f"Unknown email template: {key}")
    row = await _row_for_key(db, key)
    if row is not None:
        await db.delete(row)
        await db.flush()
    return await resolve(db, key)


async def send_templated_email(
    db: AsyncSession,
    key: str,
    to: str,
    values: dict[str, str],
) -> bool:
    """Resolve catalog/DB template, render placeholders, send. Skip if disabled."""
    if key not in CATALOG:
        logger.warning("Refusing to send unknown email template key: %s", key)
        return False
    resolved = await resolve(db, key)
    if not resolved.enabled:
        logger.info("Email template %s disabled; skipping send to %s", key, to)
        return False
    subject = render(resolved.subject, values)
    body_text = render(resolved.body_text, values)
    body_html = render(resolved.body_html, values) if resolved.body_html else None
    return await send_email(
        to=to,
        subject=subject,
        body_text=body_text,
        body_html=body_html,
    )
