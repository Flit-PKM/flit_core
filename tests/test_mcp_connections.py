"""Tests for GET/DELETE /mcp/connections (MCP OAuth session management)."""

from __future__ import annotations

import base64
import hashlib
import secrets

import pytest
from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from auth.password import get_password_hash
from service.mcp_oauth import (
    create_pending_authorization,
    issue_authorization_code,
    set_pending_user,
)
from service.user import create_user
from test_mcp import _mcp_headers


def _login(test_client, email: str, password: str) -> str:
    r = test_client.post(
        "/api/auth/login-json",
        json={"email": email, "password": password},
    )
    assert r.status_code == status.HTTP_200_OK
    return r.json()["access_token"]


async def _oauth_tokens_via_pkce(
    test_db_session: AsyncSession,
    test_client,
    user_id: int,
) -> dict:
    verifier = secrets.token_urlsafe(32)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()

    pending = await create_pending_authorization(
        test_db_session,
        state=f"conn-state-{secrets.token_urlsafe(8)}",
        client_id="mcp-dev",
        redirect_uri="http://127.0.0.1:8080/oauth/callback",
        resource="http://testserver/mcp",
        scope="read",
        code_challenge=challenge,
        code_challenge_method="S256",
    )
    await set_pending_user(test_db_session, pending, user_id)
    code = await issue_authorization_code(test_db_session, pending)
    await test_db_session.commit()

    token_resp = test_client.post(
        "/mcp/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "http://127.0.0.1:8080/oauth/callback",
            "client_id": "mcp-dev",
            "code_verifier": verifier,
            "resource": "http://testserver/mcp",
        },
    )
    assert token_resp.status_code == 200
    return token_resp.json()


@pytest.mark.asyncio
async def test_list_mcp_connections_after_oauth(
    mcp_enabled,
    test_client,
    test_db_session: AsyncSession,
    sample_user_data: dict,
):
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user = await create_user(test_db_session, user_data)
    await test_db_session.commit()

    await _oauth_tokens_via_pkce(test_db_session, test_client, user.id)

    jwt = _login(test_client, sample_user_data["email"], sample_user_data["password"])
    list_resp = test_client.get(
        "/mcp/connections",
        headers={"Authorization": f"Bearer {jwt}"},
    )
    assert list_resp.status_code == 200
    connections = list_resp.json()
    assert len(connections) >= 1
    conn = connections[0]
    assert conn["client_id"] == "mcp-dev"
    assert conn["client_name"] == "MCP Development Client"
    assert conn["scopes"] == "read"
    assert "expires_at" in conn


@pytest.mark.asyncio
async def test_delete_mcp_connection_revokes_access_and_refresh(
    mcp_enabled,
    test_client,
    test_db_session: AsyncSession,
    sample_user_data: dict,
):
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user = await create_user(test_db_session, user_data)
    await test_db_session.commit()

    tokens = await _oauth_tokens_via_pkce(test_db_session, test_client, user.id)
    access_token = tokens["access_token"]
    refresh_token = tokens["refresh_token"]

    jwt = _login(test_client, sample_user_data["email"], sample_user_data["password"])
    list_resp = test_client.get(
        "/mcp/connections",
        headers={"Authorization": f"Bearer {jwt}"},
    )
    connection_id = list_resp.json()[0]["id"]

    delete_resp = test_client.delete(
        f"/mcp/connections/{connection_id}",
        headers={"Authorization": f"Bearer {jwt}"},
    )
    assert delete_resp.status_code == 204

    mcp_resp = test_client.post(
        "/mcp",
        headers=_mcp_headers(access_token),
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )
    assert mcp_resp.status_code == 401

    refresh_resp = test_client.post(
        "/mcp/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "resource": "http://testserver/mcp",
        },
    )
    assert refresh_resp.status_code == 401

    list_after = test_client.get(
        "/mcp/connections",
        headers={"Authorization": f"Bearer {jwt}"},
    )
    assert list_after.json() == []


@pytest.mark.asyncio
async def test_delete_mcp_connection_not_found(
    mcp_enabled,
    test_client,
    test_db_session: AsyncSession,
    sample_user_data: dict,
):
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    await create_user(test_db_session, user_data)
    await test_db_session.commit()

    jwt = _login(test_client, sample_user_data["email"], sample_user_data["password"])
    r = test_client.delete(
        "/mcp/connections/99999",
        headers={"Authorization": f"Bearer {jwt}"},
    )
    assert r.status_code == 404
