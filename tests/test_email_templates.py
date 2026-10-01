"""Email template render, send triggers, and admin CRUD."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import status

from auth.password import get_password_hash
from config import settings
from exceptions import ConflictError
from service.email_template import CATALOG, render, upsert_template
from service.subscription import create_subscription
from service.user import create_user, grant_superuser
from service import billing


def _login(test_client, email: str, password: str) -> str:
    r = test_client.post(
        "/api/auth/login-json",
        json={"email": email, "password": password},
    )
    assert r.status_code == status.HTTP_200_OK
    return r.json()["access_token"]


async def _superuser(test_db_session, email: str = "tpladmin@example.com"):
    user = await create_user(
        test_db_session,
        {
            "username": "tpladmin",
            "email": email,
            "password_hash": get_password_hash("adminpass123"),
            "is_verified": True,
        },
    )
    await grant_superuser(test_db_session, user.id)
    await test_db_session.commit()
    return user


def test_render_known_placeholders_and_leaves_unknown():
    out = render("Hi {username}, go {link} {foo}", {"username": "Ada", "link": "https://x"})
    assert out == "Hi Ada, go https://x {foo}"


@pytest.mark.asyncio
async def test_password_register_sends_welcome_and_verify(
    test_client,
    sample_user_data: dict,
):
    mock_send = AsyncMock(return_value=True)
    with (
        patch("service.verification.public_base_url", return_value="https://core.flit-pkm.com"),
        patch("service.email_template.send_email", mock_send),
    ):
        response = test_client.post("/api/auth/register", json=sample_user_data)
    assert response.status_code == status.HTTP_201_CREATED
    assert mock_send.call_count == 2
    subjects = [c.kwargs["subject"] for c in mock_send.call_args_list]
    assert any("welcome" in s.lower() for s in subjects)
    assert any("verify" in s.lower() for s in subjects)
    assert all(c.kwargs["to"] == sample_user_data["email"] for c in mock_send.call_args_list)


@pytest.mark.asyncio
async def test_google_new_user_sends_welcome_only(test_client, monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "test.apps.googleusercontent.com")
    mock_send = AsyncMock(return_value=True)
    claims = {"email": "newgoogle-tpl@example.com", "email_verified": True}
    with (
        patch("routes.auth.verify_google_login_id_token", return_value=claims),
        patch("service.email_template.send_email", mock_send),
    ):
        response = test_client.post(
            "/api/auth/login-google",
            json={"id_token": "fake-jwt"},
        )
    assert response.status_code == status.HTTP_200_OK
    assert mock_send.call_count == 1
    assert "welcome" in mock_send.call_args.kwargs["subject"].lower()


@pytest.mark.asyncio
async def test_create_user_via_service_sends_welcome_only(test_db_session):
    mock_send = AsyncMock(return_value=True)
    with patch("service.email_template.send_email", mock_send):
        await create_user(
            test_db_session,
            {
                "username": "svcwelcome",
                "email": "svcwelcome@example.com",
                "password_hash": get_password_hash("password123"),
            },
        )
        await test_db_session.commit()
    assert mock_send.call_count == 1
    assert "welcome" in mock_send.call_args.kwargs["subject"].lower()


@pytest.mark.asyncio
async def test_disabled_welcome_skips_send(test_db_session):
    await upsert_template(test_db_session, "welcome", enabled=False)
    await test_db_session.commit()
    mock_send = AsyncMock(return_value=True)
    with patch("service.email_template.send_email", mock_send):
        await create_user(
            test_db_session,
            {
                "username": "nowelcome",
                "email": "nowelcome@example.com",
                "password_hash": get_password_hash("password123"),
            },
        )
        await test_db_session.commit()
    mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_mailing_list_subscribe_sends_confirm_duplicate_does_not(test_db_session):
    mock_send = AsyncMock(return_value=True)
    with patch("service.email_template.send_email", mock_send):
        await create_subscription(test_db_session, "list@example.com")
        await test_db_session.commit()
    assert mock_send.call_count == 1
    assert mock_send.call_args.kwargs["to"] == "list@example.com"
    assert "mailing list" in mock_send.call_args.kwargs["subject"].lower()

    mock_send.reset_mock()
    with patch("service.email_template.send_email", mock_send):
        with pytest.raises(ConflictError):
            await create_subscription(test_db_session, "list@example.com")
    mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_billing_webhook_sends_when_enabled_complete_does_not(
    test_db_session,
    sample_user_data: dict,
):
    data = sample_user_data.copy()
    data["password_hash"] = get_password_hash(data.pop("password"))
    user = await create_user(test_db_session, data)
    await test_db_session.commit()

    await upsert_template(test_db_session, "subscription.active", enabled=True)
    await test_db_session.commit()

    mock_send = AsyncMock(return_value=True)
    event = {
        "type": "subscription.active",
        "data": {
            "subscription_id": "sub_mail_1",
            "customer_id": "cust_mail",
            "metadata": {"user_id": str(user.id)},
            "product_id": "prod_x",
        },
    }
    with patch("service.email_template.send_email", mock_send):
        await billing.handle_webhook_event(test_db_session, event)
        await test_db_session.commit()
    assert mock_send.call_count == 1
    assert mock_send.call_args.kwargs["to"] == user.email

    mock_tpl = AsyncMock(return_value=True)
    mock_sub = MagicMock()
    mock_sub.subscription_id = "sub_complete_mail"
    mock_sub.status = "active"
    mock_sub.metadata = {"user_id": str(user.id)}
    mock_sub.customer_id = "cust_c"
    mock_sub.customer.customer_id = "cust_c"
    mock_sub.customer.id = "cust_c"
    mock_sub.product_id = "prod_x"
    mock_sub.next_billing_date = None
    mock_client = MagicMock()
    mock_client.subscriptions.retrieve.return_value = mock_sub

    with (
        patch("service.billing.is_plans_configured", return_value=True),
        patch("service.billing._get_dodo_client", return_value=mock_client),
        patch("service.email_template.send_templated_email", mock_tpl),
    ):
        await billing.complete_subscription(
            db=test_db_session,
            user_id=user.id,
            subscription_id="sub_complete_mail",
            status="active",
        )
    mock_tpl.assert_not_called()


@pytest.mark.asyncio
async def test_patch_then_send_uses_new_subject(test_db_session):
    await upsert_template(
        test_db_session,
        "welcome",
        subject="Hello {username}",
        body_text="Custom {email}",
    )
    await test_db_session.commit()
    mock_send = AsyncMock(return_value=True)
    with patch("service.email_template.send_email", mock_send):
        await create_user(
            test_db_session,
            {
                "username": "patched",
                "email": "patched@example.com",
                "password_hash": get_password_hash("password123"),
            },
        )
        await test_db_session.commit()
    assert mock_send.call_args.kwargs["subject"] == "Hello patched"
    assert "patched@example.com" in mock_send.call_args.kwargs["body_text"]


@pytest.mark.asyncio
async def test_admin_email_templates_crud_and_forbidden(
    test_client,
    test_db_session,
    sample_user_data: dict,
):
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    await create_user(test_db_session, user_data)
    await test_db_session.commit()
    user_token = _login(test_client, sample_user_data["email"], sample_user_data["password"])
    r = test_client.get(
        "/api/admin/email-templates",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert r.status_code == status.HTTP_403_FORBIDDEN

    await _superuser(test_db_session)
    admin_token = _login(test_client, "tpladmin@example.com", "adminpass123")
    headers = {"Authorization": f"Bearer {admin_token}"}

    listed = test_client.get("/api/admin/email-templates", headers=headers)
    assert listed.status_code == status.HTTP_200_OK
    keys = {row["key"] for row in listed.json()}
    assert keys == set(CATALOG)
    welcome = next(row for row in listed.json() if row["key"] == "welcome")
    assert welcome["is_overridden"] is False
    assert "username" in welcome["placeholders"]

    patched = test_client.patch(
        "/api/admin/email-templates/welcome",
        headers=headers,
        json={"subject": "Overridden hello", "enabled": True},
    )
    assert patched.status_code == status.HTTP_200_OK
    assert patched.json()["subject"] == "Overridden hello"
    assert patched.json()["is_overridden"] is True

    missing = test_client.get("/api/admin/email-templates/not-a-key", headers=headers)
    assert missing.status_code == status.HTTP_404_NOT_FOUND

    reset = test_client.post("/api/admin/email-templates/welcome/reset", headers=headers)
    assert reset.status_code == status.HTTP_200_OK
    assert reset.json()["is_overridden"] is False
    assert reset.json()["subject"] == CATALOG["welcome"].default_subject

    mock_send = AsyncMock(return_value=True)
    with patch("service.email_template.send_email", mock_send):
        tested = test_client.post(
            "/api/admin/email-templates/welcome/test",
            headers=headers,
        )
    assert tested.status_code == status.HTTP_200_OK
    assert tested.json()["sent"] is True
    mock_send.assert_called_once()
    assert mock_send.call_args.kwargs["to"] == "tpladmin@example.com"


@pytest.mark.asyncio
async def test_register_succeeds_when_email_unconfigured(
    test_client,
    sample_user_data: dict,
):
    sample = dict(sample_user_data)
    sample["email"] = "unconfigured@example.com"
    sample["username"] = "unconfigured"
    with patch("service.email_template.send_email", AsyncMock(return_value=False)):
        response = test_client.post("/api/auth/register", json=sample)
    assert response.status_code == status.HTTP_201_CREATED
