"""Tests for authentication flows."""

from datetime import datetime, timezone

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from models.plan_subscription import PlanSubscription
from models.user import User
from service.user import create_user
from auth.password import get_password_hash


@pytest.mark.asyncio
async def test_register_user_success(
    test_client: AsyncClient,
    test_db_session: AsyncSession,
    sample_user_data: dict,
):
    """Test successful user registration."""
    response = test_client.post("/api/auth/register", json=sample_user_data)
    
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data["email"] == sample_user_data["email"]
    assert data["username"] == sample_user_data["username"]
    assert "password" not in data
    assert "password_hash" not in data
    assert "id" in data


@pytest.mark.asyncio
async def test_register_duplicate_email(
    test_client: AsyncClient,
    test_db_session: AsyncSession,
    sample_user_data: dict,
):
    """Test registration with duplicate email fails."""
    # Create first user
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    await create_user(test_db_session, user_data)
    await test_db_session.commit()
    
    # Try to register again with same email
    response = test_client.post("/api/auth/register", json=sample_user_data)
    
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "already registered" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_login_success(
    test_client: AsyncClient,
    test_db_session: AsyncSession,
    sample_user_data: dict,
):
    """Test successful login."""
    # Create user first
    user_data = sample_user_data.copy()
    password = user_data.pop("password")
    user_data["password_hash"] = get_password_hash(password)
    user = await create_user(test_db_session, user_data)
    await test_db_session.commit()
    
    # Login
    response = test_client.post(
        "/api/auth/login-json",
        json={
            "email": sample_user_data["email"],
            "password": password,
        },
    )
    
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert len(data["access_token"]) > 0


@pytest.mark.asyncio
async def test_login_invalid_email(
    test_client: AsyncClient,
    sample_user_data: dict,
):
    """Test login with invalid email."""
    response = test_client.post(
        "/api/auth/login-json",
        json={
            "email": "nonexistent@example.com",
            "password": sample_user_data["password"],
        },
    )
    
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert "incorrect" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_login_invalid_password(
    test_client: AsyncClient,
    test_db_session: AsyncSession,
    sample_user_data: dict,
):
    """Test login with invalid password."""
    # Create user first
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    await create_user(test_db_session, user_data)
    await test_db_session.commit()
    
    # Try to login with wrong password
    response = test_client.post(
        "/api/auth/login-json",
        json={
            "email": sample_user_data["email"],
            "password": "wrongpassword",
        },
    )
    
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert "incorrect" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_login_form_data(
    test_client: AsyncClient,
    test_db_session: AsyncSession,
    sample_user_data: dict,
):
    """Test login with OAuth2 form data."""
    # Create user first
    user_data = sample_user_data.copy()
    password = user_data.pop("password")
    user_data["password_hash"] = get_password_hash(password)
    await create_user(test_db_session, user_data)
    await test_db_session.commit()
    
    # Login with form data
    response = test_client.post(
        "/api/auth/login",
        data={
            "username": sample_user_data["email"],
            "password": password,
        },
    )
    
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_token_validation(
    test_client: AsyncClient,
    test_db_session: AsyncSession,
    sample_user_data: dict,
):
    """Test that generated token can be used for authenticated requests."""
    # Create user and login
    user_data = sample_user_data.copy()
    password = user_data.pop("password")
    user_data["password_hash"] = get_password_hash(password)
    await create_user(test_db_session, user_data)
    await test_db_session.commit()
    
    login_response = test_client.post(
        "/api/auth/login-json",
        json={
            "email": sample_user_data["email"],
            "password": password,
        },
    )
    token = login_response.json()["access_token"]
    
    # Use token to access protected endpoint (current user; GET /users/ requires superuser)
    response = test_client.get(
        "/api/user/",
        headers={"Authorization": f"Bearer {token}"},
    )
    
    assert response.status_code == status.HTTP_200_OK


@pytest.mark.asyncio
async def test_invalid_token(
    test_client: AsyncClient,
):
    """Test that invalid token is rejected."""
    response = test_client.get(
        "/api/users/",
        headers={"Authorization": "Bearer invalid_token"},
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def _login(test_client, email: str, password: str) -> str:
    """Login and return access token."""
    r = test_client.post(
        "/api/auth/login-json",
        json={"email": email, "password": password},
    )
    assert r.status_code == status.HTTP_200_OK
    return r.json()["access_token"]


@pytest.mark.asyncio
async def test_get_user_includes_subscription_null_when_no_subscription(
    test_client,
    test_db_session: AsyncSession,
    sample_user_data: dict,
):
    """GET /user response includes subscription: null when user has no plan subscription."""
    user_data = sample_user_data.copy()
    password = user_data.pop("password")
    user_data["password_hash"] = get_password_hash(password)
    await create_user(test_db_session, user_data)
    await test_db_session.commit()

    token = _login(test_client, sample_user_data["email"], password)
    response = test_client.get("/api/user/", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert "subscription" in data
    assert data["subscription"] is None


@pytest.mark.asyncio
async def test_get_user_includes_subscription_when_user_has_plan_subscription(
    test_client,
    test_db_session: AsyncSession,
    sample_user_data: dict,
):
    """GET /user response includes subscription details when user has a plan subscription."""
    user_data = sample_user_data.copy()
    password = user_data.pop("password")
    user_data["password_hash"] = get_password_hash(password)
    user = await create_user(test_db_session, user_data)
    await test_db_session.flush()

    sub = PlanSubscription(
        user_id=user.id,
        dodo_subscription_id="sub_dodo_123",
        dodo_customer_id="cust_456",
        status="active",
        current_period_end=datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc),
    )
    test_db_session.add(sub)
    await test_db_session.commit()

    token = _login(test_client, sample_user_data["email"], password)
    response = test_client.get("/api/user/", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert "subscription" in data
    assert data["subscription"] is not None
    assert data["subscription"]["status"] == "active"
    assert data["subscription"]["dodo_subscription_id"] == "sub_dodo_123"
    assert "current_period_end" in data["subscription"]
    assert "2025-06-15" in data["subscription"]["current_period_end"]
