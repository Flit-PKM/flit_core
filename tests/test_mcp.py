"""Tests for MCP server, OAuth metadata, API keys, and scope enforcement."""

from __future__ import annotations

import json

import pytest
from fastapi import status

from config import settings
from flit_mcp.setup import register_mcp
from main import app
from service.mcp_api_key import create_mcp_api_key
from service.user import create_user
from auth.password import get_password_hash


@pytest.fixture
def mcp_enabled(monkeypatch, test_db_session):
    from starlette.routing import Mount

    monkeypatch.setattr(settings, "MCP_ENABLED", True)
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "http://testserver")
    monkeypatch.setattr(settings, "MCP_RATE_LIMIT_ENABLED", False)

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

    # main.py mounts the SPA at / before tests enable MCP; re-order so API/MCP win.
    spa_mount = None
    for i, route in enumerate(list(app.router.routes)):
        if isinstance(route, Mount) and route.path in ("", "/"):
            spa_mount = app.router.routes.pop(i)
            break
    import flit_mcp.setup as mcp_setup

    mcp_setup._mcp_registered = False
    app.openapi_schema = None
    register_mcp(app)
    if spa_mount is not None:
        app.router.routes.append(spa_mount)


def _mcp_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": "2025-06-18",
    }


def _tools_list(test_client, token: str) -> dict:
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list",
        "params": {},
    }
    response = test_client.post("/mcp", headers=_mcp_headers(token), json=body)
    assert response.status_code == 200
    data = response.json()
    assert "result" in data
    return data


def _tools_call(test_client, token: str, name: str, arguments: dict | None = None) -> dict:
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments or {}},
    }
    response = test_client.post("/mcp", headers=_mcp_headers(token), json=body)
    assert response.status_code == 200
    data = response.json()
    assert "result" in data or "error" in data
    return data


@pytest.mark.asyncio
async def test_oauth_protected_resource_metadata(mcp_enabled, test_client):
    response = test_client.get("/.well-known/oauth-protected-resource")
    assert response.status_code == 200
    data = response.json()
    assert data["resource"] == "http://testserver/mcp"
    assert "read" in data["scopes_supported"]


@pytest.mark.asyncio
async def test_oauth_authorization_server_metadata(mcp_enabled, test_client):
    response = test_client.get("/.well-known/oauth-authorization-server")
    assert response.status_code == 200
    data = response.json()
    assert data["issuer"] == "http://testserver"
    assert "authorization_endpoint" in data
    assert data["authorization_endpoint"] == "http://testserver/mcp/oauth/authorize"


@pytest.mark.asyncio
async def test_get_mcp_unauthenticated_returns_401_not_spa(mcp_enabled, test_client):
    """GET /mcp must hit MCP router (401), not the SPA index.html (200)."""
    response = test_client.get("/mcp")
    assert response.status_code == 401
    content_type = response.headers.get("content-type", "")
    assert "text/html" not in content_type
    assert not response.text.lstrip().startswith("<!")
    body = response.json()
    www = response.headers.get("www-authenticate", "").lower()
    assert "resource_metadata" in www or body.get("resource_metadata")
    assert body.get("error") == "Authentication required"


@pytest.mark.asyncio
async def test_mcp_list_notes_with_api_key(
    mcp_enabled, test_client, test_db_session, sample_user_data
):
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user = await create_user(test_db_session, user_data)
    await test_db_session.commit()

    _, plaintext = await create_mcp_api_key(
        test_db_session,
        user_id=user.id,
        name="test",
        scope="read write",
    )
    await test_db_session.commit()

    create_data = _tools_call(
        test_client,
        plaintext,
        "create_note",
        {"title": "MCP test note", "content": "Body for serialization test"},
    )
    assert "result" in create_data

    data = _tools_call(test_client, plaintext, "list_notes", {"limit": 10})
    assert "result" in data
    text = data["result"]["content"][0]["text"]
    notes = json.loads(text)
    assert isinstance(notes, list)
    assert len(notes) >= 1
    note = notes[0]
    assert note["title"] == "MCP test note"
    assert isinstance(note["created_at"], str)
    assert isinstance(note["updated_at"], str)
    assert "T" in note["created_at"]


@pytest.mark.asyncio
async def test_read_scope_hides_write_tools_from_list(
    mcp_enabled, test_client, test_db_session, sample_user_data
):
    from flit_mcp.tool_access import MCP_WRITE_TOOL_NAMES

    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user = await create_user(test_db_session, user_data)
    await test_db_session.commit()

    _, plaintext = await create_mcp_api_key(
        test_db_session,
        user_id=user.id,
        name="read-only-list",
        scope="read",
    )
    await test_db_session.commit()

    data = _tools_list(test_client, plaintext)
    names = {t["name"] for t in data["result"]["tools"]}
    assert "list_notes" in names
    assert "get_note" in names
    assert names.isdisjoint(MCP_WRITE_TOOL_NAMES)


@pytest.mark.asyncio
async def test_read_write_scope_lists_all_tools(
    mcp_enabled, test_client, test_db_session, sample_user_data
):
    from flit_mcp.tool_access import MCP_WRITE_TOOL_NAMES

    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user = await create_user(test_db_session, user_data)
    await test_db_session.commit()

    _, plaintext = await create_mcp_api_key(
        test_db_session,
        user_id=user.id,
        name="read-write-list",
        scope="read write",
    )
    await test_db_session.commit()

    data = _tools_list(test_client, plaintext)
    names = {t["name"] for t in data["result"]["tools"]}
    assert MCP_WRITE_TOOL_NAMES.issubset(names)


@pytest.mark.asyncio
async def test_read_scope_blocks_create_note(
    mcp_enabled, test_client, test_db_session, sample_user_data
):
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user = await create_user(test_db_session, user_data)
    await test_db_session.commit()

    _, plaintext = await create_mcp_api_key(
        test_db_session,
        user_id=user.id,
        name="read-only",
        scope="read",
    )
    await test_db_session.commit()

    data = _tools_call(
        test_client,
        plaintext,
        "create_note",
        {"title": "x", "content": "y"},
    )
    if "error" in data:
        assert "read write" in data["error"]["message"].lower()
    else:
        result = data.get("result") or {}
        assert result.get("isError") is True
        assert "read write" in result["content"][0]["text"].lower()


@pytest.mark.asyncio
async def test_mcp_api_keys_crud(
    mcp_enabled, test_client, test_db_session, sample_user_data
):
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user = await create_user(test_db_session, user_data)
    await test_db_session.commit()

    login = test_client.post(
        "/api/auth/login-json",
        json={"email": sample_user_data["email"], "password": "testpassword123"},
    )
    assert login.status_code == 200
    jwt = login.json()["access_token"]

    create_resp = test_client.post(
        "/mcp/api-keys",
        headers={"Authorization": f"Bearer {jwt}"},
        json={"name": "ci", "scope": "read"},
    )
    assert create_resp.status_code == 201
    created = create_resp.json()
    assert created["api_key"].startswith("flit_mcp_")

    list_resp = test_client.get(
        "/mcp/api-keys",
        headers={"Authorization": f"Bearer {jwt}"},
    )
    assert list_resp.status_code == 200
    assert len(list_resp.json()) >= 1

    delete_resp = test_client.delete(
        f"/mcp/api-keys/{created['id']}",
        headers={"Authorization": f"Bearer {jwt}"},
    )
    assert delete_resp.status_code == 204


@pytest.mark.asyncio
async def test_oauth_pkce_token_exchange(
    mcp_enabled, test_client, test_db_session, sample_user_data
):
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user = await create_user(test_db_session, user_data)
    await test_db_session.commit()

    import secrets
    import hashlib
    import base64
    from service.mcp_oauth import create_pending_authorization, issue_authorization_code, set_pending_user

    verifier = secrets.token_urlsafe(32)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()

    pending = await create_pending_authorization(
        test_db_session,
        state="state123",
        client_id="mcp-dev",
        redirect_uri="http://127.0.0.1:8080/oauth/callback",
        resource="http://testserver/mcp",
        scope="read",
        code_challenge=challenge,
        code_challenge_method="S256",
    )
    await set_pending_user(test_db_session, pending, user.id)
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
    body = token_resp.json()
    assert "access_token" in body
    assert body["scope"] == "read"


@pytest.mark.asyncio
async def test_oauth_token_authenticates_mcp_post(
    mcp_enabled, test_client, test_db_session, sample_user_data
):
    """PKCE-issued MCP OAuth access token must authenticate POST /mcp."""
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user = await create_user(test_db_session, user_data)
    await test_db_session.commit()

    import base64
    import hashlib
    import secrets

    from service.mcp_oauth import (
        create_pending_authorization,
        issue_authorization_code,
        set_pending_user,
    )

    verifier = secrets.token_urlsafe(32)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()

    pending = await create_pending_authorization(
        test_db_session,
        state="mcp-post-state",
        client_id="mcp-dev",
        redirect_uri="http://127.0.0.1:8080/oauth/callback",
        resource="http://testserver/mcp",
        scope="read",
        code_challenge=challenge,
        code_challenge_method="S256",
    )
    await set_pending_user(test_db_session, pending, user.id)
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
    access_token = token_resp.json()["access_token"]

    init_resp = test_client.post(
        "/mcp",
        headers=_mcp_headers(access_token),
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        },
    )
    assert init_resp.status_code == 200
    data = init_resp.json()
    assert "result" in data
    assert data["result"]["serverInfo"]["name"] == "Flit Core MCP"

    tools_resp = test_client.post(
        "/mcp",
        headers=_mcp_headers(access_token),
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    )
    assert tools_resp.status_code == 200
    tools_data = tools_resp.json()
    assert "result" in tools_data
    assert len(tools_data["result"].get("tools", [])) >= 1


def test_openapi_includes_mcp_catalog_by_default(test_client):
    app.openapi_schema = None
    response = test_client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert "/mcp/catalog" in schema["paths"]
    assert "McpJsonRpcRequest" in schema.get("components", {}).get("schemas", {})
    assert "x-mcp-tools" in schema
    assert len(schema["x-mcp-tools"]) >= 1


@pytest.mark.asyncio
async def test_openapi_includes_mcp_protocol_when_enabled(mcp_enabled, test_client):
    app.openapi_schema = None
    response = test_client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert "/mcp" in schema["paths"]
    assert "post" in schema["paths"]["/mcp"]
    post_op = schema["paths"]["/mcp"]["post"]
    assert "requestBody" in post_op
    assert "/mcp/oauth/token" in schema["paths"]


@pytest.mark.asyncio
async def test_mcp_catalog_endpoint(test_client):
    response = test_client.get("/mcp/catalog")
    assert response.status_code == 200
    data = response.json()
    assert "tools" in data
    assert len(data["tools"]) >= 1
    assert any(t["name"] == "list_notes" for t in data["tools"])
