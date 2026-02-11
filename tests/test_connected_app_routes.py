"""Tests for connected app routes (list, update, revoke)."""

import pytest
from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from auth.password import get_password_hash
from models.connected_app import ConnectedApp
from models.oauth_access_token import OAuthAccessToken
from models.oauth_refresh_token import OAuthRefreshToken
from service.user import create_user


def _login(test_client, email: str, password: str) -> str:
    r = test_client.post(
        "/api/auth/login-json",
        json={"email": email, "password": password},
    )
    assert r.status_code == status.HTTP_200_OK
    return r.json()["access_token"]


@pytest.mark.asyncio
async def test_delete_connected_app_returns_body_and_revokes_tokens(
    test_client,
    test_db_session: AsyncSession,
    sample_user_data: dict,
):
    """DELETE /connected-apps/{id} returns final state and revokes tokens."""
    # Create user
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user = await create_user(test_db_session, user_data)
    await test_db_session.commit()

    # Create a connected app
    connected_app = ConnectedApp(
        user_id=user.id,
        app_slug="flit",
        device_name="MacBook",
        platform="macOS",
        app_version="1.0.0",
        is_active=True,
    )
    test_db_session.add(connected_app)
    await test_db_session.flush()
    await test_db_session.refresh(connected_app)

    # Create associated tokens
    access_token = OAuthAccessToken(
        token="dummy-access-token",
        connected_app_id=connected_app.id,
        user_id=user.id,
        scopes="read write",
        expires_at=connected_app.created_at,
        created_at=connected_app.created_at,
    )
    test_db_session.add(access_token)
    await test_db_session.flush()

    refresh_token = OAuthRefreshToken(
        token="dummy-refresh-token",
        access_token_id=access_token.id,
        connected_app_id=connected_app.id,
        user_id=user.id,
        expires_at=connected_app.created_at,
        created_at=connected_app.created_at,
    )
    test_db_session.add(refresh_token)
    await test_db_session.flush()

    access_token.refresh_token_id = refresh_token.id
    await test_db_session.flush()
    await test_db_session.commit()

    # Authenticate as user
    token = _login(test_client, sample_user_data["email"], sample_user_data["password"])

    # Revoke connected app
    r = test_client.delete(
        f"/api/connected-apps/{connected_app.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == status.HTTP_200_OK
    data = r.json()
    assert data["id"] == connected_app.id
    assert data["is_active"] is False

    # Tokens should be revoked/invalidated
    refreshed = await test_db_session.get(OAuthAccessToken, access_token.id)
    assert refreshed is not None
    assert refreshed.revoked is True

    refreshed_rt = await test_db_session.get(OAuthRefreshToken, refresh_token.id)
    assert refreshed_rt is not None
    assert refreshed_rt.revoked_at is not None


@pytest.mark.asyncio
async def test_delete_connected_app_not_found(
    test_client,
    test_db_session: AsyncSession,
    sample_user_data: dict,
):
    """DELETE /connected-apps/{id} returns 404 when not found."""
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    await create_user(test_db_session, user_data)
    await test_db_session.commit()

    token = _login(test_client, sample_user_data["email"], sample_user_data["password"])

    r = test_client.delete(
        "/api/connected-apps/9999",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == status.HTTP_404_NOT_FOUND
    assert r.json()["detail"] == "Connected app not found"

