"""Shared UTC helpers for naive DB timestamps and aware comparisons."""

from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc_aware(dt: datetime) -> datetime:
    """Return dt as timezone-aware UTC (e.g. for SQLite-naive datetimes)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def utc_naive_now() -> datetime:
    """Naive UTC instant (matches columns without time zone)."""
    return utcnow().replace(tzinfo=None)
