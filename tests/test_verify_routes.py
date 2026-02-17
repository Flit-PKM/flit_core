"""Tests for email verification routes."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import status

from auth.password import get_password_hash
from auth.verify_token import create_verification_token
from service.user import create_user


def _login(test_client, email: str, password: str) -> str:
    """Log in and return access token."""
    r = test_client.post(
        "/api/auth/login-json",
        json={"email": email, "password": password},
    )
    assert r.status_code == status.HTTP_200_OK
    return r.json()["access_token"]


@pytest.mark.asyncio
async def test_send_verification_without_auth_returns_401(test_client):
    """GET /verify without auth returns 401."""
    response = test_client.get("/api/verify")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_send_verification_base_url_not_configured(
    test_client,
    test_db_session,
    sample_user_data: dict,
):
    """GET /verify when VERIFY_EMAIL_BASE_URL unset returns 200 with sent=false."""
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    await create_user(test_db_session, user_data)
    await test_db_session.commit()

    token = _login(test_client, sample_user_data["email"], sample_user_data["password"])
    response = test_client.get(
        "/api/verify",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["sent"] is False
    assert "detail" in data
    assert "not configured" in data["detail"].lower()


@pytest.mark.asyncio
async def test_send_verification_sends_email_when_configured(
    test_client,
    test_db_session,
    sample_user_data: dict,
):
    """GET /verify with base URL set sends email and returns sent=true."""
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user = await create_user(test_db_session, user_data)
    await test_db_session.commit()

    mock_settings = MagicMock()
    mock_settings.VERIFY_EMAIL_BASE_URL = "https://core.flit-pkm.com"
    mock_settings.VERIFY_EMAIL_EXPIRE_HOURS = 24
    mock_settings.VERIFY_EMAIL_RESEND_COOLDOWN_MINUTES = 5

    mock_send_email = AsyncMock(return_value=True)

    with (
        patch("service.verification.settings", mock_settings),
        patch("service.verification.send_email", mock_send_email),
    ):
        token = _login(test_client, sample_user_data["email"], sample_user_data["password"])
        response = test_client.get(
            "/api/verify",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["sent"] is True
    mock_send_email.assert_called_once()
    call_kwargs = mock_send_email.call_args.kwargs
    assert call_kwargs["to"] == sample_user_data["email"]
    assert "verify" in call_kwargs["subject"].lower()
    assert "core.flit-pkm.com/api/verify/" in call_kwargs["body_text"]


@pytest.mark.asyncio
async def test_send_verification_already_verified_returns_sent_true(
    test_client,
    test_db_session,
    sample_user_data: dict,
):
    """GET /verify when user already verified returns sent=true without sending email."""
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user_data["is_verified"] = True
    await create_user(test_db_session, user_data)
    await test_db_session.commit()

    mock_settings = MagicMock()
    mock_settings.VERIFY_EMAIL_BASE_URL = "https://core.flit-pkm.com"

    mock_send_email = AsyncMock(return_value=True)

    with (
        patch("service.verification.settings", mock_settings),
        patch("service.verification.send_email", mock_send_email),
    ):
        token = _login(test_client, sample_user_data["email"], sample_user_data["password"])
        response = test_client.get(
            "/api/verify",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["sent"] is True
    mock_send_email.assert_not_called()


@pytest.mark.asyncio
async def test_verify_token_valid_sets_is_verified(
    test_client,
    test_db_session,
    sample_user_data: dict,
):
    """GET /api/verify/{token} with valid token returns success=true and sets is_verified."""
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user = await create_user(test_db_session, user_data)
    await test_db_session.commit()

    verify_token_str = create_verification_token(user.id)
    response = test_client.get(f"/api/verify/{verify_token_str}")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["success"] is True
    assert data.get("detail") is None

    await test_db_session.refresh(user)
    assert user.is_verified is True


@pytest.mark.asyncio
async def test_send_verification_cooldown_returns_sent_false(
    test_client,
    test_db_session,
    sample_user_data: dict,
):
    """GET /verify within cooldown returns sent=false with detail."""
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user = await create_user(test_db_session, user_data)
    await test_db_session.commit()

    mock_settings = MagicMock()
    mock_settings.VERIFY_EMAIL_BASE_URL = "https://core.flit-pkm.com"
    mock_settings.VERIFY_EMAIL_EXPIRE_HOURS = 24
    mock_settings.VERIFY_EMAIL_RESEND_COOLDOWN_MINUTES = 5  # 5 min cooldown

    mock_send_email = AsyncMock(return_value=True)

    with (
        patch("service.verification.settings", mock_settings),
        patch("service.verification.send_email", mock_send_email),
        patch("service.verification._verification_cooldown", {user.id: 9999999999}),  # Far future
    ):
        token = _login(test_client, sample_user_data["email"], sample_user_data["password"])
        response = test_client.get(
            "/api/verify",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["sent"] is False
    assert "wait" in data.get("detail", "").lower()
    mock_send_email.assert_not_called()


@pytest.mark.asyncio
async def test_verify_token_confirm_valid_redirects_with_success(
    test_client,
    test_db_session,
    sample_user_data: dict,
):
    """GET /api/verify/{token}/confirm with valid token redirects to frontend with success=1."""
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user = await create_user(test_db_session, user_data)
    await test_db_session.commit()

    mock_settings = MagicMock()
    mock_settings.VERIFY_EMAIL_BASE_URL = "https://core.flit-pkm.com"

    verify_token_str = create_verification_token(user.id)
    with patch("routes.verify.settings", mock_settings):
        response = test_client.get(
            f"/api/verify/{verify_token_str}/confirm",
            follow_redirects=False,
        )
    assert response.status_code == status.HTTP_302_FOUND
    assert "verify?success=1" in response.headers["location"]

    await test_db_session.refresh(user)
    assert user.is_verified is True


@pytest.mark.asyncio
async def test_verify_token_confirm_invalid_redirects_with_error(
    test_client,
):
    """GET /api/verify/{token}/confirm with invalid token redirects to frontend with success=0."""
    mock_settings = MagicMock()
    mock_settings.VERIFY_EMAIL_BASE_URL = "https://core.flit-pkm.com"

    with patch("routes.verify.settings", mock_settings):
        response = test_client.get(
            "/api/verify/invalid-token/confirm",
            follow_redirects=False,
        )
    assert response.status_code == status.HTTP_302_FOUND
    assert "verify?success=0" in response.headers["location"]
    assert "error=expired" in response.headers["location"]


@pytest.mark.asyncio
async def test_verify_token_invalid_returns_failure(
    test_client,
    test_db_session,
):
    """GET /api/verify/{token} with invalid token returns success=false."""
    response = test_client.get("/api/verify/invalid-token-xyz")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["success"] is False
    assert "detail" in data
    assert "invalid" in data["detail"].lower() or "expired" in data["detail"].lower()


@pytest.mark.asyncio
async def test_verify_token_already_verified_idempotent(
    test_client,
    test_db_session,
    sample_user_data: dict,
):
    """GET /api/verify/{token} when user already verified returns success=true (idempotent)."""
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user_data["is_verified"] = True
    user = await create_user(test_db_session, user_data)
    await test_db_session.commit()

    verify_token_str = create_verification_token(user.id)
    response = test_client.get(f"/api/verify/{verify_token_str}")
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["success"] is True
