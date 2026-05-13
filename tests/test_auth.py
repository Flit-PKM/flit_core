"""Tests for authentication flows."""

from unittest.mock import AsyncMock, MagicMock, patch

from turnstile import TurnstileVerificationError

from datetime import datetime, timezone

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
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
async def test_register_with_turnstile_required_when_secret_set(
    test_client: AsyncClient,
    test_db_session: AsyncSession,
    sample_user_data: dict,
):
    """When TURNSTILE_SECRET is set, registration requires valid token; with mocked token succeeds."""
    mock_settings = MagicMock()
    mock_settings.TURNSTILE_SECRET = "test-secret"

    with (
        patch("routes.auth.settings", mock_settings),
        patch("routes.auth.verify_turnstile_token", new_callable=AsyncMock) as mock_verify,
    ):
        mock_verify.return_value = {"success": True}
        response = test_client.post(
            "/api/auth/register",
            json={**sample_user_data, "cf_turnstile_response": "mock-token"},
        )
    assert response.status_code == status.HTTP_201_CREATED
    assert response.json()["email"] == sample_user_data["email"]

    # Without token returns 400 (mock raises when token is missing)
    async def verify_side_effect(token, client_ip=None):
        if not token or not str(token).strip():
            raise TurnstileVerificationError("Missing Turnstile token")
        return {"success": True}

    with (
        patch("routes.auth.settings", mock_settings),
        patch("routes.auth.verify_turnstile_token", new_callable=AsyncMock, side_effect=verify_side_effect),
    ):
        response = test_client.post(
            "/api/auth/register",
            json=sample_user_data,
        )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    detail = response.json().get("detail", "").lower()
    assert "verification" in detail or "human" in detail


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


@pytest.mark.asyncio
async def test_login_json_rejects_oauth_only_user(
    test_client: AsyncClient,
    test_db_session: AsyncSession,
    sample_user_data: dict,
):
    """Password login returns generic 401 when the account has no password (Google-only)."""
    user_data = sample_user_data.copy()
    user_data.pop("password")
    user_data["password_hash"] = None
    await create_user(test_db_session, user_data)
    await test_db_session.commit()

    response = test_client.post(
        "/api/auth/login-json",
        json={
            "email": sample_user_data["email"],
            "password": "any-password",
        },
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert "incorrect" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_login_google_not_configured_returns_503(
    test_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "GOOGLE_OAUTH_CLIENT_ID", None)
    response = test_client.post(
        "/api/auth/login-google",
        json={"id_token": "dummy"},
    )
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert "not configured" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_login_google_invalid_token_returns_401(
    test_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "test.apps.googleusercontent.com")
    with patch(
        "routes.auth.verify_google_login_id_token",
        side_effect=ValueError("Invalid Google ID token"),
    ):
        response = test_client.post(
            "/api/auth/login-google",
            json={"id_token": "bad"},
        )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert "invalid google" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_login_google_creates_user_with_null_password(
    test_client: AsyncClient,
    test_db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "test.apps.googleusercontent.com")
    email = "newgoogle@example.com"
    claims = {"email": email, "email_verified": True}
    with patch("routes.auth.verify_google_login_id_token", return_value=claims):
        response = test_client.post(
            "/api/auth/login-google",
            json={"id_token": "fake-jwt"},
        )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"

    result = await test_db_session.execute(select(User).where(User.email == email))
    user = result.scalar_one()
    assert user.password_hash is None
    assert user.is_verified is True


@pytest.mark.asyncio
async def test_login_google_existing_password_user(
    test_client: AsyncClient,
    test_db_session: AsyncSession,
    sample_user_data: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "test.apps.googleusercontent.com")
    user_data = sample_user_data.copy()
    password = user_data.pop("password")
    user_data["password_hash"] = get_password_hash(password)
    await create_user(test_db_session, user_data)
    await test_db_session.commit()

    claims = {"email": sample_user_data["email"], "email_verified": True}
    with patch("routes.auth.verify_google_login_id_token", return_value=claims):
        response = test_client.post(
            "/api/auth/login-google",
            json={"id_token": "fake-jwt"},
        )
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_google_inactive_user_forbidden(
    test_client: AsyncClient,
    test_db_session: AsyncSession,
    sample_user_data: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "test.apps.googleusercontent.com")
    user_data = sample_user_data.copy()
    password = user_data.pop("password")
    user_data["password_hash"] = get_password_hash(password)
    user_data["is_active"] = False
    await create_user(test_db_session, user_data)
    await test_db_session.commit()

    claims = {"email": sample_user_data["email"], "email_verified": True}
    with patch("routes.auth.verify_google_login_id_token", return_value=claims):
        response = test_client.post(
            "/api/auth/login-google",
            json={"id_token": "fake-jwt"},
        )
    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert "inactive" in response.json()["detail"].lower()
