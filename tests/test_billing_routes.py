"""Tests for billing routes: /billing/plans, /billing/checkout, etc."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from auth.dependencies import get_current_active_user
from main import app


@pytest.mark.asyncio
async def test_get_plans_when_not_configured_returns_empty(test_client):
    """GET /billing/plans returns 200 with empty list when plans are not configured (no API key)."""
    with patch("service.billing.is_plans_configured", return_value=False):
        response = test_client.get("/api/billing/plans")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_get_plans_returns_plan_details_when_configured(test_client):
    """GET /billing/plans returns 200 with 2 plans when configured."""
    sample_plans = [
        {
            "product_id": "prod_monthly",
            "name": "Monthly",
            "description": "Monthly subscription",
            "image": "https://example.com/img.png",
            "is_recurring": True,
            "price": {"type": "recurring_price", "currency": "usd", "price": 999},
            "metadata": {},
            "tax_category": "saas",
            "addons": [],
            "meters": [],
            "plan_type": "monthly",
            "show_discounted_badge": False,
        },
        {
            "product_id": "prod_annual",
            "name": "Annual",
            "description": "Annual subscription",
            "image": None,
            "is_recurring": True,
            "price": {"type": "recurring_price", "currency": "usd", "price": 9999},
            "metadata": {},
            "tax_category": "saas",
            "addons": [],
            "meters": [],
            "plan_type": "annual",
            "show_discounted_badge": True,
        },
    ]

    async def mock_get_plans():
        return sample_plans

    with patch("routes.billing.get_plans", side_effect=mock_get_plans):
        response = test_client.get("/api/billing/plans")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["product_id"] == "prod_monthly"
    assert data[0]["plan_type"] == "monthly"
    assert data[0]["show_discounted_badge"] is False
    assert data[1]["plan_type"] == "annual"
    assert data[1]["show_discounted_badge"] is True


def _override_checkout_auth(user_id: int = 1, email: str = "user@example.com", username: str = "testuser"):
    """Override get_current_active_user so checkout route sees an authenticated user."""
    fake_user = MagicMock()
    fake_user.id = user_id
    fake_user.is_active = True
    fake_user.email = email
    fake_user.username = username

    async def override():
        return fake_user

    app.dependency_overrides[get_current_active_user] = override


def _clear_checkout_auth():
    """Remove the checkout auth override."""
    app.dependency_overrides.pop(get_current_active_user, None)


@pytest.mark.asyncio
async def test_checkout_requires_product_id(test_client):
    """POST /billing/checkout without product_id returns 422 (validation error)."""
    _override_checkout_auth()
    try:
        response = test_client.post("/api/billing/checkout", json={})
    finally:
        _clear_checkout_auth()
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_checkout_empty_product_id_returns_400(test_client):
    """POST /billing/checkout with empty product_id returns 400."""
    _override_checkout_auth()
    try:
        response = test_client.post(
            "/api/billing/checkout",
            json={"product_id": ""},
        )
    finally:
        _clear_checkout_auth()
    assert response.status_code == 400
    assert "product_id" in response.json().get("detail", "")


@pytest.mark.asyncio
async def test_checkout_blank_product_id_returns_400(test_client):
    """POST /billing/checkout with whitespace-only product_id returns 400."""
    _override_checkout_auth()
    try:
        response = test_client.post(
            "/api/billing/checkout",
            json={"product_id": "   "},
        )
    finally:
        _clear_checkout_auth()
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_checkout_not_configured_returns_503(test_client):
    """POST /billing/checkout when checkout not configured returns 503."""
    _override_checkout_auth()
    try:
        with patch("routes.billing.is_checkout_configured", return_value=False):
            response = test_client.post(
                "/api/billing/checkout",
                json={"product_id": "prod_abc"},
            )
    finally:
        _clear_checkout_auth()
    assert response.status_code == 503
    assert "not configured" in response.json().get("detail", "").lower()


@pytest.mark.asyncio
async def test_checkout_success_passes_product_id_to_service(test_client):
    """POST /billing/checkout with product_id calls service with that product_id and return_url, returns 200."""
    _override_checkout_auth()
    try:
        async def mock_create_checkout_session(
            user_id: int,
            product_id: str,
            return_url=None,
            customer_email=None,
            customer_name=None,
        ):
            assert product_id == "prod_chosen_plan"
            assert return_url == "https://app.example.com/success"
            assert customer_email == "user@example.com"
            assert customer_name == "testuser"
            return {"session_id": "sess_123", "checkout_url": "https://checkout.example.com/sess_123"}

        with patch("routes.billing.create_checkout_session", side_effect=mock_create_checkout_session):
            with patch("routes.billing.is_checkout_configured", return_value=True):
                response = test_client.post(
                    "/api/billing/checkout",
                    json={
                        "product_id": "prod_chosen_plan",
                        "return_url": "https://app.example.com/success",
                    },
                )
    finally:
        _clear_checkout_auth()
    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == "sess_123"
    assert data["checkout_url"] == "https://checkout.example.com/sess_123"


@pytest.mark.asyncio
async def test_checkout_disallowed_product_id_returns_400(test_client):
    """POST /billing/checkout with product_id not in allowed list returns 400."""
    _override_checkout_auth()
    try:
        mock_checkout_resp = MagicMock()
        mock_checkout_resp.session_id = "sess_xyz"
        mock_checkout_resp.checkout_url = "https://checkout.example.com/xyz"
        mock_client = MagicMock()
        mock_client.checkout_sessions.create.return_value = mock_checkout_resp

        allowed = ["prod_monthly", "prod_annual"]
        with patch("routes.billing.is_checkout_configured", return_value=True):
            with patch("service.billing.get_allowed_product_ids", return_value=allowed):
                with patch("service.billing._get_dodo_client", return_value=mock_client):
                    response = test_client.post(
                        "/api/billing/checkout",
                        json={"product_id": "prod_unknown"},
                    )
    finally:
        _clear_checkout_auth()
    assert response.status_code == 400
    assert "not an allowed plan" in response.json().get("detail", "")
    mock_client.checkout_sessions.create.assert_not_called()


@pytest.mark.asyncio
async def test_billing_complete_requires_auth(test_client):
    """POST /billing/complete without auth returns 401."""
    response = test_client.post(
        "/api/billing/complete",
        json={"subscription_id": "sub_123", "status": "active"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_billing_complete_missing_body_returns_422(test_client):
    """POST /billing/complete without body or missing fields returns 422."""
    _override_checkout_auth()
    try:
        response = test_client.post("/api/billing/complete", json={})
    finally:
        _clear_checkout_auth()
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_billing_complete_success_returns_200(test_client):
    """POST /billing/complete with valid body and auth returns 200 and ok/subscription_id/status."""
    _override_checkout_auth(user_id=1)
    try:
        mock_complete = AsyncMock(return_value=None)
        with patch("routes.billing.complete_subscription", mock_complete):
            with patch("routes.billing.is_checkout_configured", return_value=True):
                response = test_client.post(
                    "/api/billing/complete",
                    json={"subscription_id": "sub_abc", "status": "active"},
                )
    finally:
        _clear_checkout_auth()
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["subscription_id"] == "sub_abc"
    assert data["status"] == "active"
    mock_complete.assert_called_once()
    call_kwargs = mock_complete.call_args.kwargs
    assert call_kwargs["user_id"] == 1
    assert call_kwargs["subscription_id"] == "sub_abc"
    assert call_kwargs["status"] == "active"


@pytest.mark.asyncio
async def test_billing_portal_requires_auth(test_client):
    """GET /billing/portal without auth returns 401."""
    response = test_client.get("/api/billing/portal")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_billing_portal_no_subscription_returns_404(test_client):
    """GET /billing/portal when user has no subscription returns 404."""
    _override_checkout_auth()
    try:
        with patch("routes.billing.is_checkout_configured", return_value=True):
            with patch("routes.billing.get_subscription_for_user", new=AsyncMock(return_value=None)):
                response = test_client.get("/api/billing/portal")
    finally:
        _clear_checkout_auth()
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_billing_portal_success_returns_portal_url(test_client):
    """GET /billing/portal returns portal_url when user has a subscription."""
    _override_checkout_auth()
    try:
        fake_sub = MagicMock()
        fake_sub.dodo_customer_id = "cus_abc"
        mock_portal = AsyncMock(return_value={"portal_url": "https://portal.example.com/s/1"})
        with patch("routes.billing.is_checkout_configured", return_value=True):
            with patch("routes.billing.get_subscription_for_user", new=AsyncMock(return_value=fake_sub)):
                with patch("routes.billing.create_customer_portal_session", mock_portal):
                    response = test_client.get("/api/billing/portal")
    finally:
        _clear_checkout_auth()
    assert response.status_code == 200
    assert response.json()["portal_url"] == "https://portal.example.com/s/1"
    mock_portal.assert_called_once_with("cus_abc")


@pytest.mark.asyncio
async def test_dodo_webhook_no_secret_returns_503(test_client):
    """POST /billing/webhooks/dodo without webhook secret configured returns 503."""
    with patch("routes.billing.settings") as mock_settings:
        mock_settings.DODO_PAYMENTS_WEBHOOK_SECRET = None
        response = test_client.post(
            "/api/billing/webhooks/dodo",
            content=b"{}",
            headers={"Content-Type": "application/json"},
        )
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_dodo_webhook_invalid_signature_returns_401(test_client):
    """POST /billing/webhooks/dodo with bad signature returns 401."""
    with patch("routes.billing.settings") as mock_settings:
        mock_settings.DODO_PAYMENTS_WEBHOOK_SECRET = "whsec_test"
        with patch("routes.billing.unwrap_webhook", side_effect=ValueError("bad sig")):
            response = test_client.post(
                "/api/billing/webhooks/dodo",
                content=b'{"type":"subscription.active"}',
                headers={
                    "Content-Type": "application/json",
                    "webhook-id": "wh_1",
                    "webhook-signature": "bad",
                    "webhook-timestamp": "123",
                },
            )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_dodo_webhook_valid_event_returns_200(test_client):
    """POST /billing/webhooks/dodo with valid signature processes event."""
    event = {
        "type": "subscription.active",
        "data": {"subscription_id": "sub_1", "customer_id": "cus_1"},
    }
    with patch("routes.billing.settings") as mock_settings:
        mock_settings.DODO_PAYMENTS_WEBHOOK_SECRET = "whsec_test"
        with patch("routes.billing.unwrap_webhook", return_value=event):
            with patch("routes.billing.try_claim_dodo_webhook_id", new=AsyncMock(return_value=True)):
                with patch("routes.billing.handle_webhook_event", new=AsyncMock()) as mock_handle:
                    response = test_client.post(
                        "/api/billing/webhooks/dodo",
                        content=json.dumps(event).encode(),
                        headers={
                            "Content-Type": "application/json",
                            "webhook-id": "wh_valid_1",
                            "webhook-signature": "sig",
                            "webhook-timestamp": "123",
                        },
                    )
    assert response.status_code == 200
    assert response.json() == {"received": True}
    mock_handle.assert_called_once()


@pytest.mark.asyncio
async def test_dodo_webhook_duplicate_id_skips_processing(test_client):
    """Duplicate webhook-id returns 200 without calling handle_webhook_event."""
    event = {"type": "subscription.active", "data": {}}
    with patch("routes.billing.settings") as mock_settings:
        mock_settings.DODO_PAYMENTS_WEBHOOK_SECRET = "whsec_test"
        with patch("routes.billing.unwrap_webhook", return_value=event):
            with patch("routes.billing.try_claim_dodo_webhook_id", new=AsyncMock(return_value=False)):
                with patch("routes.billing.handle_webhook_event", new=AsyncMock()) as mock_handle:
                    response = test_client.post(
                        "/api/billing/webhooks/dodo",
                        content=json.dumps(event).encode(),
                        headers={
                            "Content-Type": "application/json",
                            "webhook-id": "wh_dup_1",
                            "webhook-signature": "sig",
                            "webhook-timestamp": "123",
                        },
                    )
    assert response.status_code == 200
    mock_handle.assert_not_called()
