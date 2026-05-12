"""Aggregate metrics for superuser admin dashboard."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.feedback import Feedback
from models.plan_subscription import PlanSubscription
from models.subscription import Subscription
from models.user import User
from service.billing import SUBSCRIPTION_STATUS_ACTIVE


def _utc_naive_now() -> datetime:
    """Current instant as naive UTC (for timestamp without time zone columns)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass
class AdminStatsResult:
    total_users: int
    verified_users: int
    unverified_users: int
    total_feedback: int
    total_subscribers: int
    users_new_24h: int
    users_new_7d: int
    users_new_30d: int
    feedback_new_24h: int
    feedback_new_7d: int
    subscribers_new_24h: int
    subscribers_new_7d: int
    users_active_login_24h: int
    users_active_login_7d: int
    users_active_login_30d: int
    unverified_stale_30d: int
    users_active_subscription: int


async def get_admin_stats(db: AsyncSession) -> AdminStatsResult:
    now = _utc_naive_now()
    t24 = now - timedelta(hours=24)
    t7 = now - timedelta(days=7)
    t30 = now - timedelta(days=30)

    async def scalar(q):
        r = await db.execute(q)
        return int(r.scalar_one() or 0)

    total_users = await scalar(select(func.count()).select_from(User))
    verified_users = await scalar(
        select(func.count()).select_from(User).where(User.is_verified.is_(True))
    )
    unverified_users = await scalar(
        select(func.count()).select_from(User).where(User.is_verified.is_(False))
    )
    total_feedback = await scalar(select(func.count()).select_from(Feedback))
    total_subscribers = await scalar(select(func.count()).select_from(Subscription))

    users_new_24h = await scalar(
        select(func.count()).select_from(User).where(User.created_at >= t24)
    )
    users_new_7d = await scalar(
        select(func.count()).select_from(User).where(User.created_at >= t7)
    )
    users_new_30d = await scalar(
        select(func.count()).select_from(User).where(User.created_at >= t30)
    )
    feedback_new_24h = await scalar(
        select(func.count()).select_from(Feedback).where(Feedback.created_at >= t24)
    )
    feedback_new_7d = await scalar(
        select(func.count()).select_from(Feedback).where(Feedback.created_at >= t7)
    )
    subscribers_new_24h = await scalar(
        select(func.count()).select_from(Subscription).where(Subscription.created_at >= t24)
    )
    subscribers_new_7d = await scalar(
        select(func.count()).select_from(Subscription).where(Subscription.created_at >= t7)
    )

    users_active_login_24h = await scalar(
        select(func.count()).select_from(User).where(User.last_login >= t24)
    )
    users_active_login_7d = await scalar(
        select(func.count()).select_from(User).where(User.last_login >= t7)
    )
    users_active_login_30d = await scalar(
        select(func.count()).select_from(User).where(User.last_login >= t30)
    )

    stale_pred = and_(User.is_verified.is_(False), User.last_login < t30)
    unverified_stale_30d = await scalar(select(func.count()).select_from(User).where(stale_pred))

    users_active_subscription = await scalar(
        select(func.count())
        .select_from(PlanSubscription)
        .where(PlanSubscription.status == SUBSCRIPTION_STATUS_ACTIVE)
    )

    return AdminStatsResult(
        total_users=total_users,
        verified_users=verified_users,
        unverified_users=unverified_users,
        total_feedback=total_feedback,
        total_subscribers=total_subscribers,
        users_new_24h=users_new_24h,
        users_new_7d=users_new_7d,
        users_new_30d=users_new_30d,
        feedback_new_24h=feedback_new_24h,
        feedback_new_7d=feedback_new_7d,
        subscribers_new_24h=subscribers_new_24h,
        subscribers_new_7d=subscribers_new_7d,
        users_active_login_24h=users_active_login_24h,
        users_active_login_7d=users_active_login_7d,
        users_active_login_30d=users_active_login_30d,
        unverified_stale_30d=unverified_stale_30d,
        users_active_subscription=users_active_subscription,
    )
