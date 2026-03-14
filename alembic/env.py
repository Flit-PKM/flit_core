# alembic/env.py
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import NullPool

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# -------------------------------
# Import your models' metadata
# -------------------------------
# Adjust the import path to match your project structure
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from models.base import Base  # ← your DeclarativeBase with metadata
# Import all models to register them with Base.metadata
from models import (  # noqa: F401
    AccessCode,
    AccessCodeGrant,
    Category,
    Chunk,
    ConnectedApp,
    ConnectionCode,
    Feedback,
    Note,
    NoteCategory,
    NoteSearch,
    OAuthAccessToken,
    OAuthRefreshToken,
    PlanSubscription,
    Relationship,
    Subscription,
    Superuser,
    User,
    UserEncryptionKey,
)

target_metadata = Base.metadata

# If you have multiple bases or want to exclude some tables, you can do:
# target_metadata = Base.metadata  # or a filtered MetaData()

# -------------------------------
# Override sqlalchemy.url if needed (optional but recommended)
# -------------------------------
# Pull DATABASE_URL from same place as your app (config/settings)
from config import settings  # noqa: E402

# Use the async URL your app already uses
connectable_url = settings.DATABASE_URL

# If you prefer to keep it in alembic.ini, comment the above and use:
# connectable_url = config.get_main_option("sqlalchemy.url")

# -------------------------------
# Async migration runner
# -------------------------------
def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.
    """
    url = connectable_url
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata
    )

    with context.begin_transaction():
        context.run_migrations()

async def run_async_migrations() -> None:
    """Run migrations in async mode."""
    connectable = create_async_engine(
        connectable_url,
        poolclass=NullPool,          # disables pooling — ideal for one-off migrations
        # Optional but recommended for clean migrations:
        # future=True,               # already default in 2.0+
        # echo=False,                # set to True only for debugging
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()