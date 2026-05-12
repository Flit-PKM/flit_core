"""Superuser admin routes: dashboard stats and newsletters."""

from typing import List

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from auth.dependencies import get_current_superuser
from database.session import get_async_session
from logging_config import get_logger
from models.user import User
from schemas.admin_stats import (
    AdminStatsBilling,
    AdminStatsFeedback,
    AdminStatsRead,
    AdminStatsSubscriptions,
    AdminStatsUsers,
)
from schemas.newsletter import (
    NewsletterCampaignCreate,
    NewsletterCampaignRead,
    NewsletterCampaignUpdate,
    NewsletterScheduleRequest,
)
from service.admin_stats import get_admin_stats
from service.newsletter_campaign import (
    create_campaign,
    get_campaign,
    list_campaigns,
    process_due_scheduled_campaigns,
    schedule_campaign,
    send_campaign_now,
    update_campaign_draft,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/stats", response_model=AdminStatsRead)
async def admin_stats(
    request: Request,
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_async_session),
):
    logger.info(
        "GET /admin/stats superuser=%s path=%s",
        current_user.id,
        request.url.path,
    )
    s = await get_admin_stats(db)
    return AdminStatsRead(
        users=AdminStatsUsers(
            total=s.total_users,
            verified=s.verified_users,
            unverified=s.unverified_users,
            new_last_24h=s.users_new_24h,
            new_last_7d=s.users_new_7d,
            new_last_30d=s.users_new_30d,
            active_login_last_24h=s.users_active_login_24h,
            active_login_last_7d=s.users_active_login_7d,
            active_login_last_30d=s.users_active_login_30d,
            unverified_stale_30d=s.unverified_stale_30d,
        ),
        feedback=AdminStatsFeedback(
            total=s.total_feedback,
            new_last_24h=s.feedback_new_24h,
            new_last_7d=s.feedback_new_7d,
        ),
        subscriptions=AdminStatsSubscriptions(
            total=s.total_subscribers,
            new_last_24h=s.subscribers_new_24h,
            new_last_7d=s.subscribers_new_7d,
        ),
        billing=AdminStatsBilling(
            users_with_active_plan_subscription=s.users_active_subscription,
        ),
    )


@router.post(
    "/newsletters",
    response_model=NewsletterCampaignRead,
    status_code=status.HTTP_201_CREATED,
)
async def admin_newsletter_create(
    body: NewsletterCampaignCreate,
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_async_session),
):
    row = await create_campaign(
        db,
        subject=body.subject,
        body_text=body.body_text,
        body_html=body.body_html,
        created_by=current_user.id,
    )
    return row


@router.get("/newsletters", response_model=List[NewsletterCampaignRead])
async def admin_newsletter_list(
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_async_session),
    skip: int = 0,
    limit: int = 50,
):
    return await list_campaigns(db, skip=skip, limit=limit)


@router.patch("/newsletters/{newsletter_id}", response_model=NewsletterCampaignRead)
async def admin_newsletter_patch(
    newsletter_id: int,
    body: NewsletterCampaignUpdate,
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_async_session),
):
    return await update_campaign_draft(
        db,
        newsletter_id,
        subject=body.subject,
        body_text=body.body_text,
        body_html=body.body_html,
    )


@router.post("/newsletters/{newsletter_id}/schedule", response_model=NewsletterCampaignRead)
async def admin_newsletter_schedule(
    newsletter_id: int,
    body: NewsletterScheduleRequest,
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_async_session),
):
    return await schedule_campaign(db, newsletter_id, body.scheduled_at)


@router.post("/newsletters/{newsletter_id}/send-now", response_model=NewsletterCampaignRead)
async def admin_newsletter_send_now(
    newsletter_id: int,
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_async_session),
):
    """Send immediately to all mailing-list subscribers."""
    return await send_campaign_now(db, newsletter_id)


@router.post("/newsletters/process-due", status_code=status.HTTP_200_OK)
async def admin_newsletters_process_due(
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_async_session),
):
    """Send all scheduled campaigns past their scheduled_at (for cron/workers)."""
    n = await process_due_scheduled_campaigns(db)
    return {"processed": n}
