"""Bulk prune stale unverified users (hard delete)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, exists, not_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.plan_subscription import PlanSubscription
from models.superuser import Superuser
from models.user import User
from service.billing import SUBSCRIPTION_STATUS_ACTIVE
from service.user_hard_delete import hard_delete_user


def _utc_naive_now() -> datetime:
    """Naive UTC instant (matches users.* timestamp without time zone columns)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _stale_predicate(inactive_for_days: int):
    cutoff = _utc_naive_now() - timedelta(days=inactive_for_days)
    return and_(User.is_verified.is_(False), User.last_login < cutoff)


async def select_prune_candidate_ids(
    db: AsyncSession,
    inactive_for_days: int,
) -> list[int]:
    """User IDs matching prune rules (unverified, stale, not superuser, no active subscription)."""
    stale = _stale_predicate(inactive_for_days)
    has_superuser = exists(select(Superuser.user_id).where(Superuser.user_id == User.id))
    has_active_sub = exists(
        select(PlanSubscription.id).where(
            PlanSubscription.user_id == User.id,
            PlanSubscription.status == SUBSCRIPTION_STATUS_ACTIVE,
        )
    )
    q = (
        select(User.id)
        .where(stale)
        .where(not_(has_superuser))
        .where(not_(has_active_sub))
        .order_by(User.id)
    )
    result = await db.execute(q)
    return [row[0] for row in result.all()]


async def prune_stale_unverified_users(
    db: AsyncSession,
    inactive_for_days: int,
    *,
    dry_run: bool,
    sample_limit: int = 20,
) -> tuple[int, int, list[int]]:
    """
    Returns (matched_count, deleted_count, sample_user_ids).
    When dry_run is True, deleted_count is 0 and no rows are removed.
    """
    ids = await select_prune_candidate_ids(db, inactive_for_days)
    matched = len(ids)
    sample = ids[:sample_limit]
    if dry_run or not ids:
        return matched, 0, sample
    deleted = 0
    for uid in ids:
        await hard_delete_user(db, uid)
        deleted += 1
    return matched, deleted, sample
