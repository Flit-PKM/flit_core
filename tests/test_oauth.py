"""Tests for OAuth token refresh and revoke (connect flow issues tokens)."""

import pytest
from fastapi import status


@pytest.mark.asyncio
async def test_oauth_refresh_token_invalid(
    test_client,
):
    """Refresh with invalid token returns 401."""
    r = test_client.post(
        "/oauth/token",
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
        "/oauth/token",
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
        "/oauth/revoke",
        json={
            "token": "some_token",
            "token_type_hint": "access_token",
        },
    )
    assert r.status_code == status.HTTP_200_OK
