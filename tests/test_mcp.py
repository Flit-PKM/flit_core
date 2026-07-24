"""Tests for MCP server, OAuth metadata, API keys, and scope enforcement."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import status

from config import settings
from flit_mcp.setup import register_mcp
from main import app
from models.plan_subscription import PlanSubscription
from service.billing import SUBSCRIPTION_STATUS_ACTIVE
from service.entitlement import ENTITLEMENT_REQUIRED_DETAIL, MCP_ENTITLEMENT_JSONRPC_CODE
from service.mcp_api_key import create_mcp_api_key
from service.user import create_user
from auth.password import get_password_hash
from service.access_code import activate_code, create_access_code


@pytest.fixture
def mcp_enabled(monkeypatch, test_db_session):
    from starlette.routing import Mount

    monkeypatch.setattr(settings, "MCP_ENABLED", True)
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "http://testserver")
    monkeypatch.setattr(settings, "MCP_RATE_LIMIT_ENABLED", False)
    monkeypatch.setattr("service.billing.is_billing_configured", lambda: False)

    class _TestSessionCtx:
        def __init__(self, session):
            self._session = session

        async def __aenter__(self):
            return self._session

        async def __aexit__(self, exc_type, exc, tb):
            return None

    def _test_session_factory():
        return _TestSessionCtx(test_db_session)

    for mod in (
        "database.engine",
        "flit_mcp.db",
        "flit_mcp.router_setup",
        "middleware.mcp_entitlement",
    ):
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
async def test_mcp_catalog_endpoint(test_client, monkeypatch):
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "http://testserver")
    response = test_client.get("/mcp/catalog")
    assert response.status_code == 200
    data = response.json()
    assert "tools" in data
    assert len(data["tools"]) >= 1
    assert any(t["name"] == "list_notes" for t in data["tools"])
    assert any(t["name"] == "search_tools" for t in data["tools"])

    server = data["server"]
    assert server["name"] == "Flit Core MCP"
    assert server["version"]
    assert server["capabilities"]["search_tools"] is True
    assert server["capabilities"]["max_batch_size"] == 50
    assert "full" in server["capabilities"]["return_modes"]
    assert server["base_url"] == "http://testserver/mcp"

    assert "notes" in data["groups"]
    assert "list_notes" in data["groups"]["notes"]
    assert "discovery" in data["groups"]
    assert "search_tools" in data["groups"]["discovery"]

    list_notes = next(t for t in data["tools"] if t["name"] == "list_notes")
    assert list_notes["category"] == "notes"
    assert "discovery" in list_notes["tags"]
    assert list_notes["scopes"] == "read"
    assert list_notes["short_description"]
    assert list_notes["examples"]
    assert list_notes["input_schema"]
    assert "properties" in list_notes["input_schema"]

    assert data["resources"]
    assert all(r.get("mime_type") == "application/json" for r in data["resources"])


@pytest.mark.asyncio
async def test_mcp_catalog_summary_and_filters(test_client):
    summary = test_client.get("/mcp/catalog", params={"detail": "summary"})
    assert summary.status_code == 200
    summary_data = summary.json()
    assert summary_data["tools"]
    assert all(t.get("input_schema") is None for t in summary_data["tools"])

    notes = test_client.get("/mcp/catalog", params={"group": "notes"})
    assert notes.status_code == 200
    notes_data = notes.json()
    assert notes_data["tools"]
    assert all(t["category"] == "notes" for t in notes_data["tools"])
    assert set(notes_data["groups"].keys()) <= {"notes"}

    tagged = test_client.get("/mcp/catalog", params={"tag": "graph"})
    assert tagged.status_code == 200
    tagged_data = tagged.json()
    assert tagged_data["tools"]
    assert all("graph" in t["tags"] for t in tagged_data["tools"])
    assert any(t["name"] == "query_graph" for t in tagged_data["tools"])


@pytest.mark.asyncio
async def test_mcp_docs_endpoint(test_client):
    response = test_client.get("/mcp/docs")
    assert response.status_code == 200
    assert "text/markdown" in response.headers.get("content-type", "")
    assert "Flit MCP Integration Guide" in response.text
    assert "search_tools" in response.text


@pytest.mark.asyncio
async def test_search_tools_ranks_and_respects_scope(
    mcp_enabled, test_client, test_db_session, sample_user_data
):
    from flit_mcp.tool_access import MCP_WRITE_TOOL_NAMES

    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user = await create_user(test_db_session, user_data)
    await test_db_session.commit()

    _, read_key = await create_mcp_api_key(
        test_db_session,
        user_id=user.id,
        name="search-read",
        scope="read",
    )
    _, write_key = await create_mcp_api_key(
        test_db_session,
        user_id=user.id,
        name="search-write",
        scope="read write",
    )
    await test_db_session.commit()

    write_data = _tools_call(
        test_client,
        write_key,
        "search_tools",
        {"query": "create note", "limit": 10},
    )
    assert "result" in write_data
    write_hits = json.loads(write_data["result"]["content"][0]["text"])
    assert isinstance(write_hits, list)
    assert write_hits
    assert write_hits[0]["name"] == "create_note"
    assert write_hits[0]["category"] == "notes"
    assert "input_schema" not in write_hits[0]
    assert any(h["name"] in MCP_WRITE_TOOL_NAMES for h in write_hits)

    read_data = _tools_call(
        test_client,
        read_key,
        "search_tools",
        {"query": "create note", "limit": 10},
    )
    assert "result" in read_data
    read_hits = json.loads(read_data["result"]["content"][0]["text"])
    assert all(h["name"] not in MCP_WRITE_TOOL_NAMES for h in read_hits)

    graph_data = _tools_call(
        test_client,
        read_key,
        "search_tools",
        {"query": "graph relationships", "group": "relationships", "limit": 5},
    )
    assert "result" in graph_data
    graph_hits = json.loads(graph_data["result"]["content"][0]["text"])
    assert graph_hits
    assert all(h["category"] == "relationships" for h in graph_hits)
    assert any(h["name"] == "query_graph" for h in graph_hits)


@pytest.mark.asyncio
async def test_mcp_tools_list_blocked_without_entitlement_when_billing_on(
    mcp_enabled, test_client, test_db_session, sample_user_data
):
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user = await create_user(test_db_session, user_data)
    _, api_key = await create_mcp_api_key(
        test_db_session, user_id=user.id, name="blocked", scope="read"
    )
    await test_db_session.commit()

    body = {
        "jsonrpc": "2.0",
        "id": 99,
        "method": "tools/list",
        "params": {},
    }
    with patch("service.billing.is_billing_configured", return_value=True):
        response = test_client.post(
            "/mcp",
            headers=_mcp_headers(api_key),
            json=body,
        )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == 99
    assert data["error"]["code"] == MCP_ENTITLEMENT_JSONRPC_CODE
    assert ENTITLEMENT_REQUIRED_DETAIL in data["error"]["message"]


@pytest.mark.asyncio
async def test_mcp_tools_list_allowed_with_active_subscription_when_billing_on(
    mcp_enabled, test_client, test_db_session, sample_user_data
):
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user = await create_user(test_db_session, user_data)
    sub = PlanSubscription(
        user_id=user.id,
        dodo_subscription_id="sub_mcp_test",
        dodo_customer_id="cus_mcp",
        status=SUBSCRIPTION_STATUS_ACTIVE,
        product_id="prod_mcp",
        current_period_end=datetime.now(timezone.utc) + timedelta(days=30),
    )
    test_db_session.add(sub)
    _, api_key = await create_mcp_api_key(
        test_db_session, user_id=user.id, name="subscribed", scope="read"
    )
    await test_db_session.commit()

    with patch("service.billing.is_billing_configured", return_value=True):
        data = _tools_list(test_client, api_key)
    assert "result" in data
    assert "tools" in data["result"]


@pytest.mark.asyncio
async def test_mcp_tools_list_allowed_with_access_grant_when_billing_on(
    mcp_enabled, test_client, test_db_session, sample_user_data
):
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user = await create_user(test_db_session, user_data)
    admin_data = {
        "username": "admin_mcp",
        "email": "admin_mcp@example.com",
        "password_hash": get_password_hash("adminpass123"),
        "is_verified": False,
    }
    admin = await create_user(test_db_session, admin_data)
    access_code = await create_access_code(
        db=test_db_session, period_weeks=4, created_by=admin.id
    )
    await activate_code(db=test_db_session, code=access_code.code, user_id=user.id)
    _, api_key = await create_mcp_api_key(
        test_db_session, user_id=user.id, name="grant", scope="read"
    )
    await test_db_session.commit()

    with patch("service.billing.is_billing_configured", return_value=True):
        data = _tools_list(test_client, api_key)
    assert "result" in data
    assert "tools" in data["result"]


@pytest.mark.asyncio
async def test_mcp_api_key_create_allowed_without_entitlement_when_billing_on(
    mcp_enabled, test_client, test_db_session, sample_user_data
):
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    await create_user(test_db_session, user_data)
    await test_db_session.commit()

    login = test_client.post(
        "/api/auth/login-json",
        json={"email": sample_user_data["email"], "password": "testpassword123"},
    )
    assert login.status_code == 200
    jwt = login.json()["access_token"]

    with patch("service.billing.is_billing_configured", return_value=True):
        create_resp = test_client.post(
            "/mcp/api-keys",
            headers={"Authorization": f"Bearer {jwt}"},
            json={"name": "no-entitlement", "scope": "read"},
        )
    assert create_resp.status_code == 201
    assert create_resp.json()["api_key"].startswith("flit_mcp_")


async def _mcp_rw_key(test_db_session, sample_user_data) -> tuple[Any, str]:
    from auth.password import get_password_hash
    from service.mcp_api_key import create_mcp_api_key
    from service.user import create_user

    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user = await create_user(test_db_session, user_data)
    await test_db_session.commit()
    _, plaintext = await create_mcp_api_key(
        test_db_session,
        user_id=user.id,
        name="phase1",
        scope="read write",
    )
    await test_db_session.commit()
    return user, plaintext


def _parse_tool_result(data: dict) -> Any:
    assert "result" in data, data
    return json.loads(data["result"]["content"][0]["text"])


@pytest.mark.asyncio
async def test_list_notes_return_mode_metadata(
    mcp_enabled, test_client, test_db_session, sample_user_data
):
    _, token = await _mcp_rw_key(test_db_session, sample_user_data)
    _tools_call(
        test_client,
        token,
        "create_note",
        {"title": "Meta test", "content": "Secret long content for metadata mode"},
    )
    data = _tools_call(
        test_client,
        token,
        "list_notes",
        {"search": "Meta test", "return_mode": "metadata", "limit": 5},
    )
    notes = _parse_tool_result(data)
    assert len(notes) >= 1
    note = notes[0]
    assert "content" not in note
    assert note["content_length"] > 0
    assert "snippet" in note


@pytest.mark.asyncio
async def test_list_notes_pinned_only(
    mcp_enabled, test_client, test_db_session, sample_user_data
):
    _, token = await _mcp_rw_key(test_db_session, sample_user_data)
    _tools_call(
        test_client,
        token,
        "create_note",
        {"title": "Pinned note", "content": "Pinned body", "pinned": True},
    )
    _tools_call(
        test_client,
        token,
        "create_note",
        {"title": "Unpinned note", "content": "Unpinned body", "pinned": False},
    )
    data = _tools_call(
        test_client,
        token,
        "list_notes",
        {"pinned_only": True, "limit": 100},
    )
    notes = _parse_tool_result(data)
    titles = {n["title"] for n in notes}
    assert "Pinned note" in titles
    assert "Unpinned note" not in titles
    assert all(n["pinned"] for n in notes)


@pytest.mark.asyncio
async def test_append_to_note(
    mcp_enabled, test_client, test_db_session, sample_user_data
):
    _, token = await _mcp_rw_key(test_db_session, sample_user_data)
    created = _parse_tool_result(
        _tools_call(
            test_client,
            token,
            "create_note",
            {"title": "Log", "content": "Line one"},
        )
    )
    updated = _parse_tool_result(
        _tools_call(
            test_client,
            token,
            "append_to_note",
            {"note_id": created["id"], "content": "Line two"},
        )
    )
    assert updated["content"] == "Line one\n\nLine two"
    assert updated["version"] == created["version"] + 1


@pytest.mark.asyncio
async def test_get_notes_batch_with_missing_ids(
    mcp_enabled, test_client, test_db_session, sample_user_data
):
    _, token = await _mcp_rw_key(test_db_session, sample_user_data)
    a = _parse_tool_result(
        _tools_call(
            test_client,
            token,
            "create_note",
            {"title": "Note A", "content": "A"},
        )
    )
    b = _parse_tool_result(
        _tools_call(
            test_client,
            token,
            "create_note",
            {"title": "Note B", "content": "B"},
        )
    )
    result = _parse_tool_result(
        _tools_call(
            test_client,
            token,
            "get_notes",
            {"note_ids": [a["id"], b["id"], 999999], "return_mode": "metadata"},
        )
    )
    assert len(result["found"]) == 2
    assert 999999 in result["missing_ids"]
    assert all("content" not in n for n in result["found"])


@pytest.mark.asyncio
async def test_query_graph_traversal(
    mcp_enabled, test_client, test_db_session, sample_user_data
):
    _, token = await _mcp_rw_key(test_db_session, sample_user_data)
    root = _parse_tool_result(
        _tools_call(
            test_client,
            token,
            "create_note",
            {"title": "Root", "content": "Root content"},
        )
    )
    child = _parse_tool_result(
        _tools_call(
            test_client,
            token,
            "create_note",
            {"title": "Child", "content": "Child content"},
        )
    )
    _tools_call(
        test_client,
        token,
        "create_relationship",
        {
            "note_a_id": root["id"],
            "note_b_id": child["id"],
            "type": "REFERENCES",
        },
    )
    graph = _parse_tool_result(
        _tools_call(
            test_client,
            token,
            "query_graph",
            {
                "starting_id": root["id"],
                "relation_type": "REFERENCES",
                "max_depth": 2,
            },
        )
    )
    assert graph["starting_id"] == root["id"]
    assert graph["return_format"] == "flat"
    node_titles = {n["title"] for n in graph["nodes"]}
    assert "Root" in node_titles
    assert "Child" in node_titles
    assert all("depth" in n for n in graph["nodes"])
    assert graph["nodes"][0]["depth"] == 0
    assert len(graph["edges"]) >= 1
    assert graph["edges"][0]["type"] == "REFERENCES"


@pytest.mark.asyncio
async def test_query_graph_tree_format(
    mcp_enabled, test_client, test_db_session, sample_user_data
):
    _, token = await _mcp_rw_key(test_db_session, sample_user_data)
    root = _parse_tool_result(
        _tools_call(
            test_client,
            token,
            "create_note",
            {"title": "Root", "content": "Root content"},
        )
    )
    child = _parse_tool_result(
        _tools_call(
            test_client,
            token,
            "create_note",
            {"title": "Child", "content": "Child content"},
        )
    )
    _tools_call(
        test_client,
        token,
        "create_relationship",
        {
            "note_a_id": root["id"],
            "note_b_id": child["id"],
            "type": "REFERENCES",
        },
    )
    graph = _parse_tool_result(
        _tools_call(
            test_client,
            token,
            "query_graph",
            {
                "starting_id": root["id"],
                "return_format": "tree",
                "max_depth": 2,
            },
        )
    )
    assert graph["return_format"] == "tree"
    assert "nodes" not in graph
    assert "edges" not in graph
    tree_root = graph["root"]
    assert tree_root["title"] == "Root"
    assert tree_root["depth"] == 0
    assert len(tree_root["children"]) == 1
    child_node = tree_root["children"][0]
    assert child_node["title"] == "Child"
    assert child_node["depth"] == 1
    assert child_node["via_type"] == "REFERENCES"
    assert child_node["children"] == []


@pytest.mark.asyncio
async def test_get_note_not_found_actionable_message(
    mcp_enabled, test_client, test_db_session, sample_user_data
):
    _, token = await _mcp_rw_key(test_db_session, sample_user_data)
    data = _tools_call(test_client, token, "get_note", {"note_id": 424242})
    if "error" in data:
        assert "list_notes" in data["error"]["message"]
    else:
        assert data["result"].get("isError") is True
        assert "list_notes" in data["result"]["content"][0]["text"]


@pytest.mark.asyncio
async def test_read_scope_hides_append_to_note(
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
        name="read-only-append",
        scope="read",
    )
    await test_db_session.commit()

    data = _tools_list(test_client, plaintext)
    names = {t["name"] for t in data["result"]["tools"]}
    assert "append_to_note" not in names
    assert "append_to_note" in MCP_WRITE_TOOL_NAMES

