"""MCP OAuth Dynamic Client Registration tests."""

from __future__ import annotations

import hashlib
import base64
import secrets
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import status
from starlette.routing import Mount

from config import settings
from flit_mcp.oauth.dcr import load_registered_oauth_client
from main import app
from models.plan_subscription import PlanSubscription
from service.billing import SUBSCRIPTION_STATUS_ACTIVE


@pytest.fixture
def mcp_dcr_env(monkeypatch, test_db_session):
    monkeypatch.setattr(settings, "ENVIRONMENT", "test")
    monkeypatch.setattr(settings, "MCP_ENABLED", True)
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "http://testserver")
    monkeypatch.setattr(settings, "MCP_RATE_LIMIT_ENABLED", False)
    monkeypatch.setattr(settings, "MCP_OAUTH_CIMD_ENABLED", True)
    monkeypatch.setattr(settings, "MCP_OAUTH_DCR_ENABLED", True)

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


def _pkce_pair():
    verifier = secrets.token_urlsafe(32)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def test_metadata_includes_registration_endpoint_when_dcr_enabled(mcp_dcr_env, test_client):
    app.openapi_schema = None
    resp = test_client.get("/.well-known/oauth-authorization-server")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("registration_endpoint") == "http://testserver/mcp/oauth/register"


def test_post_register_without_jwt(mcp_dcr_env, test_client):
    resp = test_client.post(
        "/mcp/oauth/register",
        json={
            "client_name": "Test MCP App",
            "redirect_uris": ["http://127.0.0.1:9999/callback"],
            "token_endpoint_auth_method": "none",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["client_id"].startswith("mcp_reg_")
    assert body["client_secret_expires_at"] == 0


def test_post_register_invalid_redirect(mcp_dcr_env, test_client):
    resp = test_client.post(
        "/mcp/oauth/register",
        json={
            "client_name": "Bad",
            "redirect_uris": ["ftp://evil.example/cb"],
        },
    )
    assert resp.status_code == 400


def test_post_register_disabled(monkeypatch, mcp_dcr_env, test_client):
    monkeypatch.setattr(settings, "MCP_OAUTH_DCR_ENABLED", False)
    resp = test_client.post(
        "/mcp/oauth/register",
        json={
            "client_name": "X",
            "redirect_uris": ["http://127.0.0.1:1/cb"],
        },
    )
    assert resp.status_code == 404


def test_dynamic_authorize_requires_client_name(mcp_dcr_env, test_client):
    verifier, challenge = _pkce_pair()
    resp = test_client.get(
        "/mcp/oauth/authorize",
        params={
            "client_id": "dynamic",
            "redirect_uri": "http://127.0.0.1:9999/callback",
            "response_type": "code",
            "state": "s1",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "resource": "http://testserver/mcp",
        },
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_browser_connect_and_token_exchange(
    mcp_dcr_env,
    test_client,
    test_db_session,
    sample_user_data,
):
    from auth.password import get_password_hash
    from service.user import create_user

    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user = await create_user(test_db_session, user_data)
    from datetime import datetime, timedelta, timezone

    sub = PlanSubscription(
        user_id=user.id,
        dodo_subscription_id="sub_test",
        dodo_customer_id="cus_test",
        status=SUBSCRIPTION_STATUS_ACTIVE,
        product_id="prod_test",
        current_period_end=datetime.now(timezone.utc) + timedelta(days=30),
    )
    test_db_session.add(sub)
    await test_db_session.flush()

    monkeypatch_billing = pytest.MonkeyPatch()
    monkeypatch_billing.setattr(
        "flit_mcp.oauth.dcr.is_billing_configured",
        lambda: True,
    )
    try:
        verifier, challenge = _pkce_pair()
        state = "connect-state"
        client_name = "My Desktop Agent"

        auth_resp = test_client.get(
            "/mcp/oauth/authorize",
            params={
                "client_id": "dynamic",
                "client_name": client_name,
                "redirect_uri": "http://127.0.0.1:9999/callback",
                "response_type": "code",
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "resource": "http://testserver/mcp",
                "scope": "read",
            },
        )
        assert auth_resp.status_code == 200
        assert client_name in auth_resp.text

        login_resp = test_client.post(
            "/mcp/oauth/login",
            data={
                "state": state,
                "email": sample_user_data["email"],
                "password": "testpassword123",
            },
        )
        assert login_resp.status_code == 200
        assert "Authorize access" in login_resp.text

        consent_resp = test_client.post(
            "/mcp/oauth/consent",
            data={"state": state, "action": "allow"},
            follow_redirects=False,
        )
        assert consent_resp.status_code == 302
        location = consent_resp.headers["location"]
        parsed = urlparse(location)
        qs = parse_qs(parsed.query)
        assert "code" in qs
        assert qs["state"][0] == state
        assert qs["client_id"][0].startswith("mcp_reg_")
        registered_client_id = qs["client_id"][0]

        token_resp = test_client.post(
            "/mcp/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": qs["code"][0],
                "redirect_uri": "http://127.0.0.1:9999/callback",
                "client_id": registered_client_id,
                "code_verifier": verifier,
                "resource": "http://testserver/mcp",
            },
        )
        assert token_resp.status_code == 200
        assert "access_token" in token_resp.json()

        loaded = await load_registered_oauth_client(test_db_session, registered_client_id)
        assert loaded is not None
        assert loaded.name == client_name
    finally:
        monkeypatch_billing.undo()


@pytest.mark.asyncio
async def test_dynamic_connect_requires_subscription_when_billing_configured(
    mcp_dcr_env,
    test_client,
    test_db_session,
    sample_user_data,
):
    from auth.password import get_password_hash
    from service.user import create_user

    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    await create_user(test_db_session, user_data)
    await test_db_session.flush()

    monkeypatch_billing = pytest.MonkeyPatch()
    monkeypatch_billing.setattr(
        "flit_mcp.oauth.dcr.is_billing_configured",
        lambda: True,
    )
    try:
        verifier, challenge = _pkce_pair()
        state = "no-sub-state"

        test_client.get(
            "/mcp/oauth/authorize",
            params={
                "client_id": "dynamic",
                "client_name": "No Sub App",
                "redirect_uri": "http://127.0.0.1:8888/callback",
                "response_type": "code",
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "resource": "http://testserver/mcp",
            },
        )
        login_resp = test_client.post(
            "/mcp/oauth/login",
            data={
                "state": state,
                "email": sample_user_data["email"],
                "password": "testpassword123",
            },
        )
        assert login_resp.status_code == 200
        assert "subscription is required" in login_resp.text.lower()
    finally:
        monkeypatch_billing.undo()
