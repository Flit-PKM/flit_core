"""Admin outbound webhooks: CRUD, signing, emit-on-commit, test fire."""

from unittest.mock import patch

import httpx
import pytest
from fastapi import status

from auth.password import get_password_hash
from service.admin_webhook import (
    ADMIN_EVENT_TYPES,
    EVENT_USER_SIGNUP,
    EVENT_WEBHOOK_TEST,
    build_envelope,
    build_sample_payload,
    dispatch_pending_admin_webhooks,
    emit_admin_event,
    mask_secret,
    sign_body,
    validate_event_types,
    validate_webhook_url,
)
from service.user import create_user, grant_superuser
from exceptions import ValidationError


def _login_json(test_client, email: str, password: str) -> str:
    r = test_client.post(
        "/api/auth/login-json",
        json={"email": email, "password": password},
    )
    assert r.status_code == status.HTTP_200_OK
    return r.json()["access_token"]


@pytest.mark.asyncio
async def _superuser_token(test_client, test_db_session, username: str, email: str) -> str:
    admin = await create_user(
        test_db_session,
        {
            "username": username,
            "email": email,
            "password_hash": get_password_hash("adminpass123"),
            "is_verified": True,
        },
    )
    await grant_superuser(test_db_session, admin.id)
    await test_db_session.commit()
    return _login_json(test_client, email, "adminpass123")


def test_sign_body_stable():
    sig = sign_body("s3cret", b'{"a":1}')
    assert sig.startswith("sha256=")
    assert sig == sign_body("s3cret", b'{"a":1}')
    assert sig != sign_body("other", b'{"a":1}')


def test_mask_secret():
    assert mask_secret(None) == (False, None)
    assert mask_secret("") == (False, None)
    assert mask_secret("abcd") == (True, "abcd")
    assert mask_secret("supersecret") == (True, "cret")


def test_validate_event_types():
    assert validate_event_types(["user.signup", "feedback.created"]) == [
        "user.signup",
        "feedback.created",
    ]
    with pytest.raises(ValidationError):
        validate_event_types([])
    with pytest.raises(ValidationError):
        validate_event_types(["not.a.real.event"])


def test_validate_webhook_url():
    assert validate_webhook_url("https://hooks.example.com/x") == (
        "https://hooks.example.com/x"
    )
    with pytest.raises(ValidationError):
        validate_webhook_url("ftp://bad.example")
    with pytest.raises(ValidationError):
        validate_webhook_url("not-a-url")


def test_sample_payloads_cover_catalog():
    for et in ADMIN_EVENT_TYPES:
        data = build_sample_payload(et)
        assert isinstance(data, dict)
        env = build_envelope(et, data)
        assert env["type"] == et
        assert "id" in env and "created_at" in env


@pytest.mark.asyncio
async def test_webhook_crud_and_masking(test_client, test_db_session):
    token = await _superuser_token(
        test_client, test_db_session, "whadmin", "whadmin@example.com"
    )
    headers = {"Authorization": f"Bearer {token}"}

    create = test_client.post(
        "/api/admin/webhooks",
        headers=headers,
        json={
            "name": "Monitor",
            "url": "https://hooks.example.com/flit",
            "events": ["user.signup", "webhook.test"],
            "secret": "my-secret-value",
            "enabled": True,
        },
    )
    assert create.status_code == status.HTTP_201_CREATED
    body = create.json()
    assert body["name"] == "Monitor"
    assert body["secret_set"] is True
    assert body["secret_last4"] == "alue"
    assert "secret" not in body
    wid = body["id"]

    listed = test_client.get("/api/admin/webhooks", headers=headers)
    assert listed.status_code == status.HTTP_200_OK
    assert any(w["id"] == wid for w in listed.json())

    types = test_client.get("/api/admin/webhooks/event-types", headers=headers)
    assert types.status_code == status.HTTP_200_OK
    assert "user.signup" in types.json()["event_types"]

    patched = test_client.patch(
        f"/api/admin/webhooks/{wid}",
        headers=headers,
        json={"enabled": False, "clear_secret": True},
    )
    assert patched.status_code == status.HTTP_200_OK
    assert patched.json()["enabled"] is False
    assert patched.json()["secret_set"] is False

    deleted = test_client.delete(f"/api/admin/webhooks/{wid}", headers=headers)
    assert deleted.status_code == status.HTTP_204_NO_CONTENT


@pytest.mark.asyncio
async def test_webhook_forbidden_for_non_superuser(test_client, test_db_session):
    await create_user(
        test_db_session,
        {
            "username": "normie",
            "email": "normie@example.com",
            "password_hash": get_password_hash("password123"),
            "is_verified": True,
        },
    )
    await test_db_session.commit()
    token = _login_json(test_client, "normie@example.com", "password123")
    r = test_client.get(
        "/api/admin/webhooks",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.asyncio
async def test_emit_on_signup_posts_to_matching_endpoint(test_client, test_db_session):
    token = await _superuser_token(
        test_client, test_db_session, "emitadmin", "emitadmin@example.com"
    )
    headers = {"Authorization": f"Bearer {token}"}
    create = test_client.post(
        "/api/admin/webhooks",
        headers=headers,
        json={
            "name": "Signups",
            "url": "https://hooks.example.com/signup",
            "events": [EVENT_USER_SIGNUP],
            "secret": "hook-secret",
            "enabled": True,
        },
    )
    assert create.status_code == status.HTTP_201_CREATED

    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    with patch("service.admin_webhook.httpx.AsyncClient", side_effect=client_factory):
        reg = test_client.post(
            "/api/auth/register",
            json={
                "username": "newbie",
                "email": "newbie@example.com",
                "password": "password123",
            },
        )
        assert reg.status_code in (
            status.HTTP_200_OK,
            status.HTTP_201_CREATED,
        )

    assert len(captured) == 1
    req = captured[0]
    assert str(req.url) == "https://hooks.example.com/signup"
    assert req.headers.get("X-Flit-Event") == EVENT_USER_SIGNUP
    assert req.headers.get("X-Flit-Signature", "").startswith("sha256=")
    payload = req.read()
    import json

    body = json.loads(payload)
    assert body["type"] == EVENT_USER_SIGNUP
    assert body["data"]["email"] == "newbie@example.com"


@pytest.mark.asyncio
async def test_no_post_when_no_matching_events(test_client, test_db_session):
    token = await _superuser_token(
        test_client, test_db_session, "nomatch", "nomatch@example.com"
    )
    headers = {"Authorization": f"Bearer {token}"}
    test_client.post(
        "/api/admin/webhooks",
        headers=headers,
        json={
            "name": "Feedback only",
            "url": "https://hooks.example.com/fb",
            "events": ["feedback.created"],
            "enabled": True,
        },
    )

    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    with patch("service.admin_webhook.httpx.AsyncClient", side_effect=client_factory):
        await emit_admin_event(
            test_db_session,
            EVENT_USER_SIGNUP,
            {"user_id": 99, "email": "x@y.com", "username": "x"},
        )
        pending = test_db_session.info.pop("admin_webhook_events", [])
        await dispatch_pending_admin_webhooks(pending)

    assert captured == []


@pytest.mark.asyncio
async def test_fire_test_event_awaits_delivery(test_client, test_db_session):
    token = await _superuser_token(
        test_client, test_db_session, "testfire", "testfire@example.com"
    )
    headers = {"Authorization": f"Bearer {token}"}
    create = test_client.post(
        "/api/admin/webhooks",
        headers=headers,
        json={
            "name": "Disabled target",
            "url": "https://hooks.example.com/test",
            "events": ["feedback.created"],
            "enabled": False,
            "secret": "abc",
        },
    )
    wid = create.json()["id"]

    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(201, json={"received": True})

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    with patch("service.admin_webhook.httpx.AsyncClient", side_effect=client_factory):
        r = test_client.post(
            f"/api/admin/webhooks/{wid}/test",
            headers=headers,
            json={"event_type": "user.signup"},
        )

    assert r.status_code == status.HTTP_200_OK
    data = r.json()
    assert data["ok"] is True
    assert data["status_code"] == 201
    assert data["event_type"] == "user.signup"
    assert data["error"] is None
    assert len(captured) == 1
    import json

    body = json.loads(captured[0].read())
    assert body["type"] == "user.signup"
    assert "email" in body["data"]

    with patch("service.admin_webhook.httpx.AsyncClient", side_effect=client_factory):
        r2 = test_client.post(
            f"/api/admin/webhooks/{wid}/test",
            headers=headers,
            json={},
        )
    assert r2.json()["event_type"] == EVENT_WEBHOOK_TEST
