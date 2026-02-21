"""Tests for password reset routes."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import status

from auth.password import get_password_hash
from auth.password_reset_token import create_password_reset_token
from service.user import create_user


@pytest.mark.asyncio
async def test_request_reset_unknown_email_returns_sent_true(
    test_client,
    test_db_session,
):
    """POST /password-reset/request with unknown email returns 200 sent=true (no leak)."""
    mock_settings = MagicMock()
    mock_settings.VERIFY_EMAIL_BASE_URL = "https://core.flit-pkm.com"
    mock_settings.PASSWORD_RESET_COOLDOWN_MINUTES = 5

    with patch("service.password_reset.settings", mock_settings):
        response = test_client.post(
            "/api/password-reset/request",
            json={"email": "nonexistent@example.com"},
        )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["sent"] is True
    assert data.get("detail") is None


@pytest.mark.asyncio
async def test_request_reset_unverified_email_returns_sent_true_no_email_sent(
    test_client,
    test_db_session,
    sample_user_data: dict,
):
    """POST /password-reset/request with unverified email returns sent=true but does not send email (no leak)."""
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user_data["is_verified"] = False
    await create_user(test_db_session, user_data)
    await test_db_session.commit()

    mock_settings = MagicMock()
    mock_settings.VERIFY_EMAIL_BASE_URL = "https://core.flit-pkm.com"
    mock_settings.PASSWORD_RESET_COOLDOWN_MINUTES = 5

    mock_send_email = AsyncMock(return_value=True)

    with (
        patch("service.password_reset.settings", mock_settings),
        patch("service.password_reset.send_email", mock_send_email),
    ):
        response = test_client.post(
            "/api/password-reset/request",
            json={"email": sample_user_data["email"]},
        )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["sent"] is True
    mock_send_email.assert_not_called()


@pytest.mark.asyncio
async def test_request_reset_base_url_not_configured(
    test_client,
    test_db_session,
    sample_user_data: dict,
):
    """POST /password-reset/request when VERIFY_EMAIL_BASE_URL unset returns sent=false."""
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    await create_user(test_db_session, user_data)
    await test_db_session.commit()

    response = test_client.post(
        "/api/password-reset/request",
        json={"email": sample_user_data["email"]},
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["sent"] is False
    assert "detail" in data
    assert "not configured" in data["detail"].lower()


@pytest.mark.asyncio
async def test_request_reset_known_email_sends(
    test_client,
    test_db_session,
    sample_user_data: dict,
):
    """POST /password-reset/request with known email sends reset link."""
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user_data["is_verified"] = True
    await create_user(test_db_session, user_data)
    await test_db_session.commit()

    mock_settings = MagicMock()
    mock_settings.VERIFY_EMAIL_BASE_URL = "https://core.flit-pkm.com"
    mock_settings.PASSWORD_RESET_EXPIRE_HOURS = 1
    mock_settings.PASSWORD_RESET_COOLDOWN_MINUTES = 5

    mock_send_email = AsyncMock(return_value=True)

    with (
        patch("service.password_reset.settings", mock_settings),
        patch("service.password_reset.send_email", mock_send_email),
    ):
        response = test_client.post(
            "/api/password-reset/request",
            json={"email": sample_user_data["email"]},
        )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["sent"] is True
    mock_send_email.assert_called_once()
    call_kwargs = mock_send_email.call_args.kwargs
    assert call_kwargs["to"] == sample_user_data["email"]
    assert "reset" in call_kwargs["subject"].lower()
    assert "core.flit-pkm.com/api/password-reset/" in call_kwargs["body_text"]


@pytest.mark.asyncio
async def test_request_reset_cooldown_returns_sent_false(
    test_client,
    test_db_session,
    sample_user_data: dict,
):
    """POST /password-reset/request within cooldown returns sent=false."""
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user_data["is_verified"] = True
    user = await create_user(test_db_session, user_data)
    await test_db_session.commit()

    mock_settings = MagicMock()
    mock_settings.VERIFY_EMAIL_BASE_URL = "https://core.flit-pkm.com"
    mock_settings.PASSWORD_RESET_EXPIRE_HOURS = 1
    mock_settings.PASSWORD_RESET_COOLDOWN_MINUTES = 5

    mock_send_email = AsyncMock(return_value=True)
    normalized = sample_user_data["email"].lower().strip()

    with (
        patch("service.password_reset.settings", mock_settings),
        patch("service.password_reset.send_email", mock_send_email),
        patch(
            "service.password_reset._password_reset_cooldown",
            {normalized: 9999999999},
        ),
    ):
        response = test_client.post(
            "/api/password-reset/request",
            json={"email": sample_user_data["email"]},
        )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["sent"] is False
    assert "wait" in data.get("detail", "").lower()
    mock_send_email.assert_not_called()


@pytest.mark.asyncio
async def test_confirm_redirect_valid_redirects(
    test_client,
    test_db_session,
    sample_user_data: dict,
):
    """GET /password-reset/{token}/confirm with valid token redirects to reset-password?token=."""
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user = await create_user(test_db_session, user_data)
    await test_db_session.commit()

    mock_settings = MagicMock()
    mock_settings.VERIFY_EMAIL_BASE_URL = "https://core.flit-pkm.com"

    token = create_password_reset_token(user.id)
    with patch("routes.password_reset.settings", mock_settings):
        response = test_client.get(
            f"/api/password-reset/{token}/confirm",
            follow_redirects=False,
        )
    assert response.status_code == status.HTTP_302_FOUND
    assert "reset-password?token=" in response.headers["location"]


@pytest.mark.asyncio
async def test_confirm_redirect_invalid_redirects_with_error(
    test_client,
):
    """GET /password-reset/{token}/confirm with invalid token redirects with error=expired."""
    mock_settings = MagicMock()
    mock_settings.VERIFY_EMAIL_BASE_URL = "https://core.flit-pkm.com"

    with patch("routes.password_reset.settings", mock_settings):
        response = test_client.get(
            "/api/password-reset/invalid-token/confirm",
            follow_redirects=False,
        )
    assert response.status_code == status.HTTP_302_FOUND
    assert "reset-password?error=expired" in response.headers["location"]


@pytest.mark.asyncio
async def test_confirm_reset_valid_updates_password(
    test_client,
    test_db_session,
    sample_user_data: dict,
):
    """POST /password-reset/confirm with valid token updates password."""
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user = await create_user(test_db_session, user_data)
    await test_db_session.commit()

    token = create_password_reset_token(user.id)
    response = test_client.post(
        "/api/password-reset/confirm",
        json={"token": token, "new_password": "NewSecurePass123!"},
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["success"] is True

    # Verify login with new password works
    login_response = test_client.post(
        "/api/auth/login-json",
        json={"email": sample_user_data["email"], "password": "NewSecurePass123!"},
    )
    assert login_response.status_code == status.HTTP_200_OK
    assert "access_token" in login_response.json()


@pytest.mark.asyncio
async def test_request_reset_requires_turnstile_when_secret_set(
    test_client,
    test_db_session,
):
    """POST /password-reset/request when TURNSTILE_SECRET set requires valid token; with token succeeds."""
    # Use unique email to avoid cooldown from other tests (module-level _password_reset_cooldown)
    email = "turnstile_test@example.com"
    user_data = {
        "username": "turnstileuser",
        "email": email,
        "password_hash": get_password_hash("SecurePass123!"),
    }
    await create_user(test_db_session, user_data)
    await test_db_session.commit()

    mock_settings = MagicMock()
    mock_settings.TURNSTILE_SECRET = "test-secret"
    mock_settings.VERIFY_EMAIL_BASE_URL = "https://core.flit-pkm.com"
    mock_settings.PASSWORD_RESET_EXPIRE_HOURS = 1
    mock_settings.PASSWORD_RESET_COOLDOWN_MINUTES = 5

    mock_send_email = AsyncMock(return_value=True)

    # With valid mocked token, request succeeds
    with (
        patch("routes.password_reset.settings", mock_settings),
        patch("routes.password_reset.verify_turnstile_token", new_callable=AsyncMock) as mock_verify,
        patch("service.password_reset.settings", mock_settings),
        patch("service.password_reset.send_email", mock_send_email),
    ):
        mock_verify.return_value = {"success": True}
        response = test_client.post(
            "/api/password-reset/request",
            json={"email": email, "cf_turnstile_response": "mock-token"},
        )
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["sent"] is True

    # Without token returns 400
    async def verify_side_effect(token, client_ip=None):
        from turnstile import TurnstileVerificationError
        if not token or not str(token).strip():
            raise TurnstileVerificationError("Missing Turnstile token")
        return {"success": True}

    with (
        patch("routes.password_reset.settings", mock_settings),
        patch("routes.password_reset.verify_turnstile_token", new_callable=AsyncMock, side_effect=verify_side_effect),
    ):
        response = test_client.post(
            "/api/password-reset/request",
            json={"email": email},
        )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    detail = response.json().get("detail", "").lower()
    assert "verification" in detail or "human" in detail


@pytest.mark.asyncio
async def test_confirm_reset_invalid_returns_failure(
    test_client,
):
    """POST /password-reset/confirm with invalid token returns success=false."""
    response = test_client.post(
        "/api/password-reset/confirm",
        json={"token": "invalid-token", "new_password": "NewSecurePass123!"},
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["success"] is False
    assert "detail" in data


@pytest.mark.asyncio
async def test_confirm_reset_short_password_returns_422(test_client):
    """POST /password-reset/confirm with password < 8 chars returns 422."""
    response = test_client.post(
        "/api/password-reset/confirm",
        json={"token": "any-token", "new_password": "short"},
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
