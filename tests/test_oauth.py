"""Tests for OAuth token refresh and revoke (connect flow issues tokens)."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import status
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from auth.password import get_password_hash
from config import settings
from models.connected_app import ConnectedApp
from service.oauth import issue_tokens_for_connected_app, validate_access_token
from service.user import create_user


@pytest.mark.asyncio
async def test_oauth_refresh_token_invalid(
    test_client,
):
    """Refresh with invalid token returns 401."""
    r = test_client.post(
        "/api/oauth/token",
        json={
            "grant_type": "refresh_token",
            "refresh_token": "invalid_refresh_token",
        },
    )
    assert r.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_oauth_refresh_token_wrong_grant(
    test_client,
):
    """Unsupported grant_type returns 400."""
    r = test_client.post(
        "/api/oauth/token",
        json={
            "grant_type": "authorization_code",
            "code": "x",
        },
    )
    assert r.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.asyncio
async def test_oauth_revoke_token(
    test_client,
):
    """Revoke returns 200 even if token unknown (per OAuth spec)."""
    r = test_client.post(
        "/api/oauth/revoke",
        json={
            "token": "some_token",
            "token_type_hint": "access_token",
        },
    )
    assert r.status_code == status.HTTP_200_OK


@pytest.mark.asyncio
async def test_validate_access_token_requires_db_row(
    test_db_session: AsyncSession,
    sample_user_data: dict,
):
    """JWT alone is not enough — missing or revoked DB row must fail."""
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user = await create_user(test_db_session, user_data)
    app = ConnectedApp(
        user_id=user.id,
        app_slug="flit",
        device_name="Test Device",
        platform="test",
        app_version="1.0",
    )
    test_db_session.add(app)
    await test_db_session.flush()

    access, _ = await issue_tokens_for_connected_app(
        test_db_session, app.id, user.id
    )
    await test_db_session.commit()
    assert await validate_access_token(test_db_session, access.token) == (
        app.id,
        user.id,
    )

    access.revoked = True
    await test_db_session.commit()
    assert await validate_access_token(test_db_session, access.token) is None

    orphan = jwt.encode(
        {
            "sub": str(user.id),
            "connected_app_id": app.id,
            "scopes": "read write",
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        },
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )
    assert await validate_access_token(test_db_session, orphan) is None
