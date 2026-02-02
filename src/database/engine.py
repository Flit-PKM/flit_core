from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from config import settings

if settings.is_d1:
    engine: AsyncEngine = create_async_engine(
        settings.DATABASE_URL,
        echo=settings.ENVIRONMENT == "development",
        poolclass=NullPool,
        connect_args={"timeout": 30},
    )
else:
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=settings.ENVIRONMENT == "development",
        pool_pre_ping=True,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
    )

AsyncSessionFactory = async_sessionmaker(
    bind = engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=True,
)