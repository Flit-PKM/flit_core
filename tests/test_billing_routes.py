"""Tests for billing routes: /billing/plans, /billing/checkout, etc."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from auth.dependencies import get_current_active_user
from main import app


@pytest.mark.asyncio
async def test_get_plans_when_not_configured_returns_empty(test_client):
    """GET /billing/plans returns 200 with empty list when plans are not configured (no API key)."""
    with patch("service.billing.is_plans_configured", return_value=False):
        response = test_client.get("/billing/plans")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_get_plans_returns_plan_details_when_configured(test_client):
    """GET /billing/plans returns 200 with 4 plans when configured."""
    sample_plans = [
        {
            "product_id": "prod_monthly_core_ai",
            "name": "Monthly Core+AI",
            "description": "Monthly subscription",
            "image": "https://example.com/img.png",
            "is_recurring": True,
            "price": {"type": "recurring_price", "currency": "usd", "price": 999},
            "metadata": {},
            "tax_category": "saas",
            "addons": [],
            "meters": [],
            "plan_type": "monthly_core_ai",
            "show_discounted_badge": False,
            "includes_encryption": False,
        },
        {
            "product_id": "prod_monthly_core_ai_enc",
            "name": "Monthly Core+AI+Encryption",
            "description": "Monthly with encryption",
            "image": None,
            "is_recurring": True,
            "price": {"type": "recurring_price", "currency": "usd", "price": 1199},
            "metadata": {},
            "tax_category": "saas",
            "addons": [],
            "meters": [],
            "plan_type": "monthly_core_ai_encryption",
            "show_discounted_badge": False,
            "includes_encryption": True,
        },
        {
            "product_id": "prod_annual_core_ai",
            "name": "Annual Core+AI",
            "description": "Annual subscription",
            "image": None,
            "is_recurring": True,
            "price": {"type": "recurring_price", "currency": "usd", "price": 9999},
            "metadata": {},
            "tax_category": "saas",
            "addons": [],
            "meters": [],
            "plan_type": "annual_core_ai",
            "show_discounted_badge": True,
            "includes_encryption": False,
        },
        {
            "product_id": "prod_annual_core_ai_enc",
            "name": "Annual Core+AI+Encryption",
            "description": "Annual with encryption",
            "image": None,
            "is_recurring": True,
            "price": {"type": "recurring_price", "currency": "usd", "price": 11999},
            "metadata": {},
            "tax_category": "saas",
            "addons": [],
            "meters": [],
            "plan_type": "annual_core_ai_encryption",
            "show_discounted_badge": True,
            "includes_encryption": True,
        },
    ]

    async def mock_get_plans():
        return sample_plans

    with patch("routes.billing.get_plans", side_effect=mock_get_plans):
        response = test_client.get("/billing/plans")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 4
    assert data[0]["product_id"] == "prod_monthly_core_ai"
    assert data[0]["plan_type"] == "monthly_core_ai"
    assert data[0]["show_discounted_badge"] is False
    assert data[0]["includes_encryption"] is False
    assert data[1]["plan_type"] == "monthly_core_ai_encryption"
    assert data[1]["includes_encryption"] is True
    assert data[2]["plan_type"] == "annual_core_ai"
    assert data[2]["show_discounted_badge"] is True
    assert data[3]["plan_type"] == "annual_core_ai_encryption"
    assert data[3]["show_discounted_badge"] is True
    assert data[3]["includes_encryption"] is True


def _override_checkout_auth(user_id: int = 1):
    """Override get_current_active_user so checkout route sees an authenticated user."""
    fake_user = MagicMock()
    fake_user.id = user_id
    fake_user.is_active = True

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
        response = test_client.post("/billing/checkout", json={})
    finally:
        _clear_checkout_auth()
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_checkout_empty_product_id_returns_400(test_client):
    """POST /billing/checkout with empty product_id returns 400."""
    _override_checkout_auth()
    try:
        response = test_client.post(
            "/billing/checkout",
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
            "/billing/checkout",
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
                "/billing/checkout",
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
        async def mock_create_checkout_session(user_id: int, product_id: str, return_url=None):
            assert product_id == "prod_chosen_plan"
            assert return_url == "https://app.example.com/success"
            return {"session_id": "sess_123", "checkout_url": "https://checkout.example.com/sess_123"}

        with patch("routes.billing.create_checkout_session", side_effect=mock_create_checkout_session):
            with patch("routes.billing.is_checkout_configured", return_value=True):
                response = test_client.post(
                    "/billing/checkout",
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

        allowed = ["prod_m_core_ai", "prod_m_core_ai_enc", "prod_a_core_ai", "prod_a_core_ai_enc"]
        with patch("routes.billing.is_checkout_configured", return_value=True):
            with patch("service.billing.get_allowed_product_ids", return_value=allowed):
                with patch("service.billing._get_dodo_client", return_value=mock_client):
                    response = test_client.post(
                        "/billing/checkout",
                        json={"product_id": "prod_unknown"},
                    )
    finally:
        _clear_checkout_auth()
    assert response.status_code == 400
    assert "not an allowed plan" in response.json().get("detail", "")
    mock_client.checkout_sessions.create.assert_not_called()
