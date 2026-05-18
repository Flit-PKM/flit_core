from __future__ import annotations

import time
from collections import defaultdict
from threading import Lock

from config import settings
from exceptions import BusinessLogicError

_lock = Lock()
_buckets: dict[str, list[float]] = defaultdict(list)


def _parse_limit(limit: str) -> tuple[int, int]:
    """Parse slowapi-style limit like '120/minute'."""
    count_str, _, period = limit.partition("/")
    count = int(count_str)
    period = period.lower()
    if period in ("minute", "min"):
        return count, 60
    if period in ("hour", "hr"):
        return count, 3600
    if period in ("second", "sec"):
        return count, 1
    return count, 60


def check_mcp_rate_limit(user_id: int) -> None:
    if not settings.MCP_RATE_LIMIT_ENABLED:
        return
    max_calls, window_secs = _parse_limit(settings.MCP_RATE_LIMIT)
    key = f"user:{user_id}"
    now = time.monotonic()
    cutoff = now - window_secs
    with _lock:
        hits = _buckets[key]
        _buckets[key] = [t for t in hits if t > cutoff]
        if len(_buckets[key]) >= max_calls:
            raise BusinessLogicError(
                "MCP rate limit exceeded. Try again later."
            )
        _buckets[key].append(now)
