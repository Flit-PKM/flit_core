"""Tests for subscription service and API."""

import pytest
from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession
from unittest.mock import AsyncMock, patch

from auth.password import get_password_hash
from exceptions import ConflictError, NotFoundError
from service.subscription import (
    create_subscription,
    delete_subscription_by_email,
    get_all_subscriptions,
    get_subscription_by_email,
)
from service.user import create_user, grant_superuser


def _login(test_client, email: str, password: str) -> str:
    r = test_client.post(
        "/api/auth/login-json",
        json={"email": email, "password": password},
    )
    assert r.status_code == status.HTTP_200_OK
    return r.json()["access_token"]


# --- Service tests ---


@pytest.mark.asyncio
async def test_create_subscription_success(test_db_session: AsyncSession):
    """Create subscription stores normalized email."""
    sub = await create_subscription(test_db_session, "  User@Example.COM  ")
    await test_db_session.commit()
    assert sub.id is not None
    assert sub.email == "user@example.com"
    assert sub.created_at is not None


@pytest.mark.asyncio
async def test_create_subscription_duplicate_raises_conflict(test_db_session: AsyncSession):
    """Duplicate email raises ConflictError."""
    await create_subscription(test_db_session, "dup@example.com")
    await test_db_session.commit()
    with pytest.raises(ConflictError) as exc_info:
        await create_subscription(test_db_session, "dup@example.com")
    assert "already subscribed" in str(exc_info.value.detail).lower()


@pytest.mark.asyncio
async def test_get_all_subscriptions(test_db_session: AsyncSession):
    """get_all_subscriptions returns list with pagination."""
    await create_subscription(test_db_session, "a@example.com")
    await create_subscription(test_db_session, "b@example.com")
    await test_db_session.commit()
    all_subs = await get_all_subscriptions(test_db_session, skip=0, limit=10)
    assert len(all_subs) == 2
    emails = {s.email for s in all_subs}
    assert emails == {"a@example.com", "b@example.com"}


@pytest.mark.asyncio
async def test_get_subscription_by_email(test_db_session: AsyncSession):
    """get_subscription_by_email is case-insensitive."""
    await create_subscription(test_db_session, "find@example.com")
    await test_db_session.commit()
    found = await get_subscription_by_email(test_db_session, "FIND@example.com")
    assert found is not None
    assert found.email == "find@example.com"
    missing = await get_subscription_by_email(test_db_session, "missing@example.com")
    assert missing is None


@pytest.mark.asyncio
async def test_delete_subscription_by_email_success(test_db_session: AsyncSession):
    """delete_subscription_by_email removes existing email."""
    await create_subscription(test_db_session, "remove@example.com")
    await test_db_session.commit()
    await delete_subscription_by_email(test_db_session, "remove@example.com")
    await test_db_session.commit()
    found = await get_subscription_by_email(test_db_session, "remove@example.com")
    assert found is None


@pytest.mark.asyncio
async def test_delete_subscription_by_email_not_found(test_db_session: AsyncSession):
    """delete_subscription_by_email raises NotFoundError when email not on list."""
    with pytest.raises(NotFoundError) as exc_info:
        await delete_subscription_by_email(test_db_session, "notonlist@example.com")
    assert "not on list" in str(exc_info.value.detail).lower()


# --- API tests ---


@pytest.mark.asyncio
async def test_get_subscriptions_requires_superuser(
    test_client,
    test_db_session: AsyncSession,
    sample_user_data: dict,
):
    """GET /subscriptions/ returns 403 for non-superuser."""
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    await create_user(test_db_session, user_data)
    await test_db_session.commit()
    token = _login(test_client, sample_user_data["email"], sample_user_data["password"])
    response = test_client.get(
        "/api/subscriptions/",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.asyncio
async def test_get_subscriptions_superuser_returns_list(
    test_client,
    test_db_session: AsyncSession,
    sample_user_data: dict,
):
    """GET /subscriptions/ returns 200 and list for superuser."""
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user = await create_user(test_db_session, user_data)
    await test_db_session.commit()
    await grant_superuser(test_db_session, user.id)
    await test_db_session.commit()
    token = _login(test_client, sample_user_data["email"], sample_user_data["password"])
    await create_subscription(test_db_session, "sub@example.com")
    await test_db_session.commit()
    response = test_client.get(
        "/api/subscriptions/",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["email"] == "sub@example.com"
    assert "id" in data[0]
    assert "created_at" in data[0]


@pytest.mark.asyncio
async def test_subscribe_without_turnstile_token_returns_400(test_client):
    """POST /subscriptions/ without valid Turnstile token returns 400."""
    response = test_client.post(
        "/api/subscriptions/",
        json={"email": "new@example.com", "cf_turnstile_response": None},
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    detail = response.json().get("detail", "").lower()
    assert "verification" in detail or "failed" in detail or "human" in detail


@pytest.mark.asyncio
async def test_subscribe_with_mocked_turnstile_success(
    test_client,
    test_db_session: AsyncSession,
):
    """POST /subscriptions/ with mocked Turnstile returns 201 and creates subscription."""
    with patch("routes.subscription.verify_turnstile_token", new_callable=AsyncMock) as mock_verify:
        mock_verify.return_value = {"success": True}
        response = test_client.post(
            "/api/subscriptions/",
            json={
                "email": "subscriber@example.com",
                "cf_turnstile_response": "mock-token",
            },
        )
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data["email"] == "subscriber@example.com"
    assert "id" in data
    assert "created_at" in data
    mock_verify.assert_called_once()


@pytest.mark.asyncio
async def test_subscribe_duplicate_returns_409(
    test_client,
    test_db_session: AsyncSession,
):
    """POST /subscriptions/ with already subscribed email returns 409."""
    await create_subscription(test_db_session, "dup@example.com")
    await test_db_session.commit()
    with patch("routes.subscription.verify_turnstile_token", new_callable=AsyncMock):
        response = test_client.post(
            "/api/subscriptions/",
            json={
                "email": "dup@example.com",
                "cf_turnstile_response": "mock-token",
            },
        )
    assert response.status_code == status.HTTP_409_CONFLICT
    assert "already" in response.json().get("detail", "").lower()


@pytest.mark.asyncio
async def test_unsubscribe_success(test_client, test_db_session: AsyncSession):
    """DELETE /subscriptions/ with email on list returns 204."""
    await create_subscription(test_db_session, "unsub@example.com")
    await test_db_session.commit()
    response = test_client.request(
        "DELETE",
        "/api/subscriptions/",
        json={"email": "unsub@example.com"},
    )
    assert response.status_code == status.HTTP_204_NO_CONTENT
    found = await get_subscription_by_email(test_db_session, "unsub@example.com")
    assert found is None


@pytest.mark.asyncio
async def test_unsubscribe_email_not_on_list_returns_404(test_client):
    """DELETE /subscriptions/ with email not on list returns 404."""
    response = test_client.request(
        "DELETE",
        "/api/subscriptions/",
        json={"email": "notonlist@example.com"},
    )
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert "not on list" in response.json().get("detail", "").lower()


# --- Turnstile module tests (mocked httpx) ---


@pytest.mark.asyncio
async def test_verify_turnstile_token_missing_token():
    """verify_turnstile_token raises when token is missing."""
    from turnstile import TurnstileVerificationError, verify_turnstile_token
    with pytest.raises(TurnstileVerificationError) as exc_info:
        await verify_turnstile_token(None)
    assert "missing" in str(exc_info.value).lower() or "token" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_verify_turnstile_token_empty_token():
    """verify_turnstile_token raises when token is empty string."""
    from turnstile import TurnstileVerificationError, verify_turnstile_token
    with pytest.raises(TurnstileVerificationError):
        await verify_turnstile_token("   ")


@pytest.mark.asyncio
async def test_verify_turnstile_token_success_mocked():
    """verify_turnstile_token returns result when Cloudflare returns success."""
    from turnstile import verify_turnstile_token
    mock_response = AsyncMock()
    mock_response.raise_for_status = lambda: None
    mock_response.json = lambda: {"success": True}
    mock_post = AsyncMock(return_value=mock_response)
    mock_client = AsyncMock()
    mock_client.post = mock_post
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    with patch("turnstile.settings") as mock_settings:
        mock_settings.TURNSTILE_SECRET = "test-secret"
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await verify_turnstile_token("valid-token")
    assert result == {"success": True}
    mock_post.assert_called_once()
