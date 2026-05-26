"""MCP OAuth CIMD, resource parameter, and discovery tests."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import status
from jose import jwt as jose_jwt

from config import settings
from flit_mcp.oauth.cimd import is_cimd_client_id, resolve_cimd_client
from flit_mcp.oauth.clients import McpOAuthClient
from main import app
from service.mcp_oauth import canonical_mcp_resource, validate_mcp_access_token


@pytest.fixture
def mcp_oauth_env(monkeypatch, test_db_session):
    from starlette.routing import Mount

    monkeypatch.setattr(settings, "ENVIRONMENT", "test")
    monkeypatch.setattr(settings, "MCP_ENABLED", True)
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "http://testserver")
    monkeypatch.setattr(settings, "MCP_RATE_LIMIT_ENABLED", False)
    monkeypatch.setattr(settings, "MCP_OAUTH_CIMD_ENABLED", True)

    class _TestSessionCtx:
        def __init__(self, session):
            self._session = session

        async def __aenter__(self):
            return self._session

        async def __aexit__(self, exc_type, exc, tb):
            return None

    def _test_session_factory():
        return _TestSessionCtx(test_db_session)

    for mod in ("database.engine", "flit_mcp.db", "flit_mcp.router_setup"):
        monkeypatch.setattr(f"{mod}.AsyncSessionFactory", _test_session_factory)

    spa_mount = None
    for i, route in enumerate(list(app.router.routes)):
        if isinstance(route, Mount) and route.path in ("", "/"):
            spa_mount = app.router.routes.pop(i)
            break
    import flit_mcp.setup as mcp_setup

    mcp_setup._mcp_registered = False
    mcp_setup._catalog_registered = False
    from flit_mcp.setup import register_mcp

    register_mcp(app)
    if spa_mount is not None:
        app.router.routes.append(spa_mount)


def test_is_cimd_client_id():
    assert is_cimd_client_id("https://app.example.com/oauth/client-metadata.json")
    assert not is_cimd_client_id("mcp-dev")
    assert not is_cimd_client_id("http://app.example.com/oauth/metadata.json")
    assert not is_cimd_client_id("https://app.example.com")


def test_authorization_server_metadata_cimd_supported(mcp_oauth_env, test_client):
    app.openapi_schema = None
    resp = test_client.get("/.well-known/oauth-authorization-server")
    assert resp.status_code == 200
    assert resp.json().get("client_id_metadata_document_supported") is True
    assert "registration_endpoint" not in resp.json()


def test_mcp_401_includes_resource_metadata(mcp_oauth_env, test_client):
    resp = test_client.post(
        "/mcp",
        headers={"Content-Type": "application/json", "MCP-Protocol-Version": "2025-06-18"},
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "t", "version": "1"},
            },
        },
    )
    assert resp.status_code == 401
    assert "resource_metadata" in resp.headers.get("www-authenticate", "").lower() or resp.json().get(
        "resource_metadata"
    )


@pytest.mark.asyncio
async def test_resolve_cimd_client_from_fetch(test_db_session):
    client_id = "https://client.example.com/oauth/metadata.json"
    doc = {
        "client_id": client_id,
        "client_name": "Example MCP Client",
        "redirect_uris": ["http://127.0.0.1:9999/callback"],
        "token_endpoint_auth_method": "none",
    }

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = json.dumps(doc).encode()
    mock_response.json.return_value = doc
    mock_response.headers = {}

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch(
        "flit_mcp.oauth.cimd._resolve_host_blocks_private",
        return_value=False,
    ), patch("httpx.AsyncClient", return_value=mock_client):
        client = await resolve_cimd_client(test_db_session, client_id)

    assert client is not None
    assert client.name == "Example MCP Client"
    assert client.exact_redirect_match is True


@pytest.mark.asyncio
async def test_cimd_mismatched_client_id_rejected(test_db_session):
    client_id = "https://client.example.com/oauth/metadata.json"
    doc = {
        "client_id": "https://other.example.com/oauth/metadata.json",
        "client_name": "Bad",
        "redirect_uris": ["http://127.0.0.1:9999/callback"],
        "token_endpoint_auth_method": "none",
    }

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = json.dumps(doc).encode()
    mock_response.json.return_value = doc
    mock_response.headers = {}

    mock_http = AsyncMock()
    mock_http.get = AsyncMock(return_value=mock_response)
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=None)

    with patch(
        "flit_mcp.oauth.cimd._resolve_host_blocks_private",
        return_value=False,
    ), patch("httpx.AsyncClient", return_value=mock_http):
        client = await resolve_cimd_client(test_db_session, client_id)

    assert client is None


def test_authorize_with_cimd_client_id(mcp_oauth_env, test_client):
    client_id = "https://client.example.com/oauth/metadata.json"
    doc = {
        "client_id": client_id,
        "client_name": "Example MCP Client",
        "redirect_uris": ["http://127.0.0.1:9999/callback"],
        "token_endpoint_auth_method": "none",
    }

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = json.dumps(doc).encode()
    mock_response.json.return_value = doc
    mock_response.headers = {}

    mock_http = AsyncMock()
    mock_http.get = AsyncMock(return_value=mock_response)
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=None)

    with patch(
        "flit_mcp.oauth.routes.resolve_oauth_client",
        new_callable=AsyncMock,
        return_value=McpOAuthClient(
            client_id=client_id,
            name="Example MCP Client",
            redirect_uris=["http://127.0.0.1:9999/callback"],
            exact_redirect_match=True,
        ),
    ):
        resp = test_client.get(
            "/mcp/oauth/authorize",
            params={
                "client_id": client_id,
                "redirect_uri": "http://127.0.0.1:9999/callback",
                "response_type": "code",
                "state": "s1",
                "code_challenge": "abc",
                "code_challenge_method": "S256",
                "resource": "http://testserver/mcp",
            },
        )

    assert resp.status_code == 200
    assert "Example MCP Client" in resp.text
    assert "Connect to Flit" in resp.text


def test_authorize_unknown_opaque_client_id(mcp_oauth_env, test_client):
    resp = test_client.get(
        "/mcp/oauth/authorize",
        params={
            "client_id": "unknown-vendor-client",
            "redirect_uri": "http://127.0.0.1:8080/oauth/callback",
            "response_type": "code",
            "state": "s1",
            "code_challenge": "abc",
            "code_challenge_method": "S256",
        },
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_validate_mcp_token_requires_audience(test_db_session):
    from auth.jwt import create_access_token
    from datetime import timedelta
    from models.mcp_access_token import McpAccessToken
    from service.mcp_oauth import MCP_TOKEN_TYPE

    token_data = {
        "sub": "1",
        "scopes": "read",
        "token_type": MCP_TOKEN_TYPE,
        "jti": "jti-no-aud",
        "aud": "https://wrong.example.com/mcp",
    }
    token = create_access_token(token_data, expires_delta=timedelta(minutes=60))
    row = McpAccessToken(
        token=token,
        user_id=1,
        scopes="read",
        jti="jti-no-aud",
        expires_at=__import__("datetime").datetime.utcnow()
        + timedelta(minutes=60),
        refresh_token_id=None,
        revoked=False,
        created_at=__import__("datetime").datetime.utcnow(),
    )
    test_db_session.add(row)
    await test_db_session.flush()

    with patch.object(settings, "PUBLIC_BASE_URL", "http://testserver"):
        result = await validate_mcp_access_token(test_db_session, token)
    assert result is None


@pytest.mark.asyncio
async def test_validate_mcp_token_accepts_canonical_aud(test_db_session, monkeypatch):
    from auth.jwt import create_access_token
    from datetime import datetime, timedelta
    from models.mcp_access_token import McpAccessToken
    from service.mcp_oauth import MCP_TOKEN_TYPE

    aud = "http://testserver/mcp"
    token_data = {
        "sub": "1",
        "scopes": "read",
        "token_type": MCP_TOKEN_TYPE,
        "jti": "jti-ok",
        "aud": aud,
    }
    token = create_access_token(token_data, expires_delta=timedelta(minutes=60))
    row = McpAccessToken(
        token=token,
        user_id=1,
        scopes="read",
        jti="jti-ok",
        expires_at=datetime.utcnow() + timedelta(minutes=60),
        refresh_token_id=None,
        revoked=False,
        created_at=datetime.utcnow(),
    )
    test_db_session.add(row)
    await test_db_session.flush()

    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "http://testserver")
    result = await validate_mcp_access_token(test_db_session, token)
    assert result == (1, "read")


@pytest.mark.asyncio
async def test_validate_mcp_token_accepts_localhost_alias_aud(
    test_db_session, monkeypatch
):
    from auth.jwt import create_access_token
    from datetime import datetime, timedelta
    from models.mcp_access_token import McpAccessToken
    from service.mcp_oauth import MCP_TOKEN_TYPE, validate_mcp_access_token

    monkeypatch.setattr(settings, "ENVIRONMENT", "test")
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "http://localhost:8000")

    token_data = {
        "sub": "1",
        "scopes": "read",
        "token_type": MCP_TOKEN_TYPE,
        "jti": "jti-localhost-alias",
        "aud": "http://127.0.0.1:8000/mcp",
    }
    token = create_access_token(token_data, expires_delta=timedelta(minutes=60))
    row = McpAccessToken(
        token=token,
        user_id=1,
        scopes="read",
        jti="jti-localhost-alias",
        expires_at=datetime.utcnow() + timedelta(minutes=60),
        refresh_token_id=None,
        revoked=False,
        created_at=datetime.utcnow(),
    )
    test_db_session.add(row)
    await test_db_session.flush()

    result = await validate_mcp_access_token(test_db_session, token)
    assert result == (1, "read")
