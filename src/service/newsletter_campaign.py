"""Admin newsletter campaigns: drafts, schedule, send to mailing list."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import NotFoundError, ValidationError
from logging_config import get_logger
from models.newsletter_campaign import NewsletterCampaign, NewsletterStatus
from models.subscription import Subscription
from service.email import send_email

logger = get_logger(__name__)


async def create_campaign(
    db: AsyncSession,
    *,
    subject: str,
    body_text: str,
    body_html: Optional[str],
    created_by: int,
) -> NewsletterCampaign:
    row = NewsletterCampaign(
        subject=subject,
        body_text=body_text,
        body_html=body_html,
        status=NewsletterStatus.DRAFT.value,
        created_by=created_by,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


async def get_campaign(db: AsyncSession, campaign_id: int) -> Optional[NewsletterCampaign]:
    r = await db.execute(select(NewsletterCampaign).where(NewsletterCampaign.id == campaign_id))
    return r.scalar_one_or_none()


async def list_campaigns(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 50,
) -> List[NewsletterCampaign]:
    r = await db.execute(
        select(NewsletterCampaign)
        .order_by(NewsletterCampaign.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(r.scalars().all())


async def update_campaign_draft(
    db: AsyncSession,
    campaign_id: int,
    *,
    subject: Optional[str] = None,
    body_text: Optional[str] = None,
    body_html: Optional[str] = None,
) -> NewsletterCampaign:
    row = await get_campaign(db, campaign_id)
    if not row:
        raise NotFoundError("Newsletter not found")
    if row.status not in (NewsletterStatus.DRAFT.value, NewsletterStatus.SCHEDULED.value):
        raise ValidationError("Only draft or scheduled newsletters can be edited")
    if subject is not None:
        row.subject = subject
    if body_text is not None:
        row.body_text = body_text
    if body_html is not None:
        row.body_html = body_html
    await db.flush()
    await db.refresh(row)
    return row


async def schedule_campaign(
    db: AsyncSession,
    campaign_id: int,
    scheduled_at: datetime,
) -> NewsletterCampaign:
    row = await get_campaign(db, campaign_id)
    if not row:
        raise NotFoundError("Newsletter not found")
    if row.status == NewsletterStatus.SENT.value:
        raise ValidationError("Cannot schedule a sent newsletter")
    if scheduled_at.tzinfo is None:
        scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    if scheduled_at <= now:
        raise ValidationError("scheduled_at must be in the future")
    row.scheduled_at = scheduled_at
    row.status = NewsletterStatus.SCHEDULED.value
    await db.flush()
    await db.refresh(row)
    return row


async def send_campaign_now(
    db: AsyncSession,
    campaign_id: int,
) -> NewsletterCampaign:
    row = await get_campaign(db, campaign_id)
    if not row:
        raise NotFoundError("Newsletter not found")
    if row.status == NewsletterStatus.SENT.value:
        raise ValidationError("Newsletter already sent")
    if row.status == NewsletterStatus.CANCELLED.value:
        raise ValidationError("Cannot send a cancelled newsletter")
    sent, total = await _broadcast_to_subscribers(db, row)
    if total > 0 and sent == 0:
        raise ValidationError("Failed to deliver newsletter to any recipient")
    now = datetime.now(timezone.utc)
    row.status = NewsletterStatus.SENT.value
    row.sent_at = now
    row.scheduled_at = None
    await db.flush()
    await db.refresh(row)
    return row


async def process_due_scheduled_campaigns(db: AsyncSession) -> int:
    """Send all scheduled campaigns whose scheduled_at is in the past. Returns count sent."""
    now = datetime.now(timezone.utc)
    r = await db.execute(
        select(NewsletterCampaign).where(
            NewsletterCampaign.status == NewsletterStatus.SCHEDULED.value,
            NewsletterCampaign.scheduled_at.is_not(None),
            NewsletterCampaign.scheduled_at <= now,
        )
    )
    rows = list(r.scalars().all())
    sent_count = 0
    for row in rows:
        sent, total = await _broadcast_to_subscribers(db, row)
        if total > 0 and sent == 0:
            logger.error(
                "Newsletter campaign %s delivery failed for all recipients; leaving scheduled",
                row.id,
            )
            continue
        row.status = NewsletterStatus.SENT.value
        row.sent_at = now
        row.scheduled_at = None
        await db.flush()
        sent_count += 1
    return sent_count


async def _broadcast_to_subscribers(
    db: AsyncSession, campaign: NewsletterCampaign
) -> tuple[int, int]:
    r = await db.execute(select(Subscription.email))
    emails = [row[0] for row in r.all()]
    sent = 0
    for email in emails:
        ok = await send_email(
            to=email,
            subject=campaign.subject,
            body_text=campaign.body_text,
            body_html=campaign.body_html,
        )
        if ok:
            sent += 1
    logger.info(
        "Newsletter campaign %s sent to %s/%s recipients (email may be disabled)",
        campaign.id,
        sent,
        len(emails),
    )
    return sent, len(emails)
