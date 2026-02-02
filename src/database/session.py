from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession
from .engine import AsyncSessionFactory

async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()