#!/usr/bin/env python3
"""CLI to purge soft-deleted rows older than PURGE_SOFT_DELETED_AFTER_WEEKS.

Run from project root with: uv run python scripts/purge_soft_deleted.py
Or with PYTHONPATH=src: uv run python scripts/purge_soft_deleted.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Ensure src is on path when run from project root
_root = Path(__file__).resolve().parent.parent
_src = _root / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))


async def _main() -> None:
    from database.engine import AsyncSessionFactory
    from service.purge import purge_soft_deleted_older_than

    async with AsyncSessionFactory() as session:
        counts = await purge_soft_deleted_older_than(session)
    total = sum(counts.values())
    print(f"Purged {total} soft-deleted row(s): {counts}")
    if total > 0:
        sys.exit(0)
    sys.exit(0)


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
