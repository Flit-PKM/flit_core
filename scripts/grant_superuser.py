#!/usr/bin/env python3
"""Standalone CLI to grant superuser to a user by email or id.

Requires only DATABASE_URL in the environment (no SECRET_KEY or other app config).
Run from project root: uv run python scripts/grant_superuser.py <email_or_id>
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# Ensure src is on path when run from project root
_root = Path(__file__).resolve().parent.parent
_src = _root / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))


def _normalize_database_url(url: str) -> str:
    """Convert postgres:// or postgresql:// to postgresql+asyncpg:// if needed."""
    u = url.strip()
    if u.startswith("postgres://"):
        return "postgresql+asyncpg://" + u[len("postgres://") :]
    if u.startswith("postgresql://") and not u.startswith("postgresql+asyncpg://"):
        return "postgresql+asyncpg://" + u[len("postgresql://") :]
    return u


async def _main() -> None:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        create_async_engine,
        async_sessionmaker,
    )
    from sqlalchemy.pool import NullPool
    from sqlalchemy import func

    from models.user import User
    from models.superuser import Superuser

    if len(sys.argv) != 2:
        print("Usage: grant_superuser.py <email_or_user_id>", file=sys.stderr)
        sys.exit(2)

    identifier = sys.argv[1].strip()
    if not identifier:
        print("Error: email or user id must be non-empty", file=sys.stderr)
        sys.exit(2)

    database_url = os.environ.get("DATABASE_URL") or ""
    if not database_url.strip():
        print("Error: DATABASE_URL environment variable is not set", file=sys.stderr)
        sys.exit(1)

    url = _normalize_database_url(database_url)
    engine = create_async_engine(url, poolclass=NullPool)
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=True,
    )

    try:
        async with session_factory() as session:
            # Resolve user: by id (numeric) or by email
            user = None
            if identifier.isdigit():
                result = await session.execute(select(User).where(User.id == int(identifier)))
                user = result.scalar_one_or_none()
            else:
                email = identifier.lower().strip()
                result = await session.execute(
                    select(User).where(func.lower(User.email) == email)
                )
                user = result.scalar_one_or_none()

            if not user:
                print(f"Error: user not found for '{identifier}'", file=sys.stderr)
                sys.exit(1)

            # Already superuser?
            existing = await session.execute(
                select(Superuser).where(Superuser.user_id == user.id)
            )
            if existing.scalar_one_or_none():
                print(f"User {user.id} ({user.email}) is already a superuser.")
                sys.exit(0)

            session.add(Superuser(user_id=user.id, granted_by=None))
            await session.commit()
            print(f"Superuser granted to user {user.id} ({user.email}).")
            sys.exit(0)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        await engine.dispose()


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
