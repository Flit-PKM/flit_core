"""Pytest configuration and fixtures."""

import asyncio
from typing import AsyncGenerator, Generator

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from main import app
from database.session import get_async_session
from models.base import Base
from config import Settings


# Test database URL - using in-memory SQLite for tests
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def event_loop() -> Generator:
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def test_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Create a test database session."""
    # Create test engine
    engine = create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    
    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # Create session factory
    async_session_maker = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    
    # Create session
    async with async_session_maker() as session:
        yield session
    
    # Cleanup
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    
    await engine.dispose()


@pytest.fixture
def test_client(test_db_session: AsyncSession) -> TestClient:
    """Create a test client with overridden database session."""
    async def override_get_session():
        yield test_db_session
    
    app.dependency_overrides[get_async_session] = override_get_session
    
    with TestClient(app) as client:
        yield client
    
    app.dependency_overrides.clear()


@pytest.fixture
def test_settings() -> Settings:
    """Create test settings with test database."""
    return Settings(
        SECRET_KEY="test-secret-key-for-testing-only-minimum-32-chars",
        DB_USER="test",
        DB_PASSWORD="test",
        DB_HOST="localhost",
        DB_PORT=5432,
        DB_NAME="test",
        ENVIRONMENT="test",
        LOG_LEVEL="WARNING",
    )


@pytest.fixture
def sample_user_data() -> dict:
    """Sample user data for testing."""
    return {
        "username": "testuser",
        "email": "test@example.com",
        "password": "testpassword123",
        "is_active": True,
        "is_verified": False,
    }


@pytest.fixture
def sample_note_data() -> dict:
    """Sample note data for testing."""
    return {
        "title": "Test Note",
        "content": "This is a test note",
        "type": "BASE",
    }
