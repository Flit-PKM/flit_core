from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from .engine import AsyncSessionFactory


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionFactory() as session:
        try:
            yield session
            await session.commit()
            pending = session.info.pop("admin_webhook_events", None)
            if pending:
                from service.admin_webhook import schedule_pending_admin_webhooks

                schedule_pending_admin_webhooks(pending)
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
