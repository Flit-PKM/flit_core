#!/usr/bin/env python3
"""Soft-delete relationships whose endpoint note is already soft-deleted.

Run from project root (uses .env / DATABASE_URL like the app):

  uv run python scripts/repair_stale_relationships.py

Point at production by exporting DATABASE_URL (and DB_BACKEND=postgres if needed)
before running, e.g.:

  export DATABASE_URL='postgresql+asyncpg://...'
  export DB_BACKEND=postgres
  uv run python scripts/repair_stale_relationships.py

Dry run (no commit):

  uv run python scripts/repair_stale_relationships.py --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
_src = _root / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))


async def _main(*, dry_run: bool) -> None:
    from database.engine import AsyncSessionFactory
    from service.relationship import repair_stale_relationships

    async with AsyncSessionFactory() as session:
        count = await repair_stale_relationships(session)
        if dry_run:
            await session.rollback()
            print(f"Dry run: would repair {count} stale relationship(s) (rolled back)")
        else:
            await session.commit()
            print(f"Repaired {count} stale relationship(s)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Soft-delete relationships pointing at soft-deleted notes.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report how many rows would change without committing",
    )
    args = parser.parse_args()
    asyncio.run(_main(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
