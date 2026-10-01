"""Admin outbound webhooks: CRUD, signing, emit-on-commit, test fire."""

import base64
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
    generate_webhook_secret,
    hmac_key,
    mask_secret,
    sign_standard_webhook,
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


_HMAC_RAW = b"test-hmac-key-bytes"
_HMAC_SECRET = "whsec_" + base64.b64encode(_HMAC_RAW).decode("ascii")


def test_hmac_key_decodes_whsec_base64():
    assert hmac_key(_HMAC_SECRET) == _HMAC_RAW
    assert hmac_key(base64.b64encode(_HMAC_RAW).decode("ascii")) == _HMAC_RAW


def test_generate_webhook_secret_whsec_unique():
    a = generate_webhook_secret()
    b = generate_webhook_secret()
    assert a.startswith("whsec_")
    assert b.startswith("whsec_")
    assert a != b
    assert hmac_key(a) != hmac_key(b)
    assert len(hmac_key(a)) == 24


def test_hmac_key_utf8_fallback_for_passphrase():
    assert hmac_key("not-valid-base64!") == b"not-valid-base64!"


def test_sign_standard_webhook_v1_base64():
    body = b'{"a":1}'
    sig = sign_standard_webhook(_HMAC_SECRET, "msg_1", 1700000000, body)
    assert sig.startswith("v1,")
    assert sig == sign_standard_webhook(_HMAC_SECRET, "msg_1", 1700000000, body)
    assert sig != sign_standard_webhook(_HMAC_SECRET, "msg_1", 1700000001, body)
    payload = base64.b64decode(sig.split(",", 1)[1])
    assert len(payload) == 32


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
            "enabled": True,
        },
    )
    assert create.status_code == status.HTTP_201_CREATED
    body = create.json()
    assert body["name"] == "Monitor"
    assert body["secret_set"] is True
    assert body["secret"].startswith("whsec_")
    first_secret = body["secret"]
    assert body["secret_last4"] == first_secret[-4:]
    wid = body["id"]

    listed = test_client.get("/api/admin/webhooks", headers=headers)
    assert listed.status_code == status.HTTP_200_OK
    listed_row = next(w for w in listed.json() if w["id"] == wid)
    assert "secret" not in listed_row
    assert listed_row["secret_set"] is True

    got = test_client.get(f"/api/admin/webhooks/{wid}", headers=headers)
    assert "secret" not in got.json()

    types = test_client.get("/api/admin/webhooks/event-types", headers=headers)
    assert types.status_code == status.HTTP_200_OK
    assert "user.signup" in types.json()["event_types"]

    patched = test_client.patch(
        f"/api/admin/webhooks/{wid}",
        headers=headers,
        json={"enabled": False},
    )
    assert patched.status_code == status.HTTP_200_OK
    assert patched.json()["enabled"] is False
    assert patched.json()["secret_set"] is True
    assert "secret" not in patched.json()

    rotated = test_client.post(
        f"/api/admin/webhooks/{wid}/rotate-secret",
        headers=headers,
    )
    assert rotated.status_code == status.HTTP_200_OK
    new_secret = rotated.json()["secret"]
    assert new_secret.startswith("whsec_")
    assert new_secret != first_secret
    assert rotated.json()["secret_last4"] == new_secret[-4:]

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
            "enabled": True,
        },
    )
    assert create.status_code == status.HTTP_201_CREATED
    signing_secret = create.json()["secret"]

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
    assert req.headers.get("webhook-id")
    assert req.headers.get("webhook-timestamp")
    sig = req.headers.get("webhook-signature", "")
    assert sig.startswith("v1,")
    payload = req.read()
    import json

    expected = sign_standard_webhook(
        signing_secret,
        req.headers["webhook-id"],
        req.headers["webhook-timestamp"],
        payload,
    )
    assert sig == expected
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
