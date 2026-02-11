"""Tests for connection-code flow (request-code + exchange)."""

from datetime import datetime, timezone, timedelta

import pytest
from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from auth.password import get_password_hash
from service.connection_code import create_connection_code
from service.user import create_user


def _login(test_client, email: str, password: str) -> str:
    r = test_client.post(
        "/api/auth/login-json",
        json={"email": email, "password": password},
    )
    assert r.status_code == status.HTTP_200_OK
    return r.json()["access_token"]


@pytest.mark.asyncio
async def test_request_code_success(
    test_client,
    test_db_session: AsyncSession,
    sample_user_data: dict,
):
    """Request code -> get connection_code, expires_in."""
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    await create_user(test_db_session, user_data)
    await test_db_session.commit()

    token = _login(test_client, sample_user_data["email"], sample_user_data["password"])
    r = test_client.post(
        "/api/connect/request-code",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == status.HTTP_200_OK
    data = r.json()
    assert "connection_code" in data
    assert "expires_in" in data
    assert len(data["connection_code"]) >= 6


@pytest.mark.asyncio
async def test_request_code_no_auth(
    test_client,
    test_db_session: AsyncSession,
    sample_user_data: dict,
):
    """Request code without authentication -> 401."""
    r = test_client.post(
        "/api/connect/request-code",
        json={},
    )
    assert r.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_exchange_success(
    test_client,
    test_db_session: AsyncSession,
    sample_user_data: dict,
):
    """Request code -> exchange with device data -> tokens."""
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user = await create_user(test_db_session, user_data)
    await test_db_session.commit()

    token = _login(test_client, sample_user_data["email"], sample_user_data["password"])
    req = test_client.post(
        "/api/connect/request-code",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert req.status_code == status.HTTP_200_OK
    code = req.json()["connection_code"]

    r = test_client.post(
        "/api/connect/exchange",
        json={
            "connection_code": code,
            "app_slug": "flit",
            "device_name": "MacBook Pro",
            "platform": "macOS",
            "app_version": "1.0.0",
        },
    )
    assert r.status_code == status.HTTP_200_OK
    data = r.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "Bearer"
    assert "expires_in" in data


@pytest.mark.asyncio
async def test_exchange_invalid_code(
    test_client,
):
    """Exchange with invalid code -> 400."""
    r = test_client.post(
        "/api/connect/exchange",
        json={
            "connection_code": "INVALID1",
            "app_slug": "flit",
            "device_name": "Mac",
            "platform": "macOS",
            "app_version": "1.0.0",
        },
    )
    assert r.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.asyncio
async def test_exchange_already_used(
    test_client,
    test_db_session: AsyncSession,
    sample_user_data: dict,
):
    """Exchange same code twice -> second returns 409."""
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    await create_user(test_db_session, user_data)
    await test_db_session.commit()

    token = _login(test_client, sample_user_data["email"], sample_user_data["password"])
    req = test_client.post(
        "/api/connect/request-code",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert req.status_code == status.HTTP_200_OK
    code = req.json()["connection_code"]

    payload = {
        "connection_code": code,
        "app_slug": "flit",
        "device_name": "Mac",
        "platform": "macOS",
        "app_version": "1.0.0",
    }
    r1 = test_client.post("/api/connect/exchange", json=payload)
    assert r1.status_code == status.HTTP_200_OK

    r2 = test_client.post("/api/connect/exchange", json=payload)
    assert r2.status_code == status.HTTP_409_CONFLICT


@pytest.mark.asyncio
async def test_exchange_expired_code(
    test_client,
    test_db_session: AsyncSession,
    sample_user_data: dict,
):
    """Exchange with expired code -> 400."""
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user = await create_user(test_db_session, user_data)
    await test_db_session.commit()

    code_row = await create_connection_code(test_db_session, user.id)
    code_row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await test_db_session.flush()
    await test_db_session.commit()

    r = test_client.post(
        "/api/connect/exchange",
        json={
            "connection_code": code_row.code,
            "app_slug": "flit",
            "device_name": "Mac",
            "platform": "macOS",
            "app_version": "1.0.0",
        },
    )
    assert r.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.asyncio
async def test_connect_then_refresh(
    test_client,
    test_db_session: AsyncSession,
    sample_user_data: dict,
):
    """Full flow: request-code -> exchange -> refresh token."""
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    await create_user(test_db_session, user_data)
    await test_db_session.commit()

    token = _login(test_client, sample_user_data["email"], sample_user_data["password"])
    req = test_client.post(
        "/api/connect/request-code",
        json={"app_slug": "still"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert req.status_code == status.HTTP_200_OK
    code = req.json()["connection_code"]

    ex = test_client.post(
        "/api/connect/exchange",
        json={
            "connection_code": code,
            "app_slug": "still",
            "device_name": "iPhone",
            "platform": "iOS",
            "app_version": "2.0.0",
        },
    )
    assert ex.status_code == status.HTTP_200_OK
    refresh_token = ex.json()["refresh_token"]

    r = test_client.post(
        "/api/oauth/token",
        json={"grant_type": "refresh_token", "refresh_token": refresh_token},
    )
    assert r.status_code == status.HTTP_200_OK
    data = r.json()
    assert "access_token" in data
    assert data["token_type"] == "Bearer"
