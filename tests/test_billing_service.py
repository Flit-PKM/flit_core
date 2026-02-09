"""Tests for billing service: get_plans, _fetch_plans_from_dodo with mocked Dodo client."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.plan_subscription import PlanSubscription
from service import billing


def _make_product(product_id: str, name: str, addons: list[str] | None = None, price_type: str = "recurring_price"):
    """Build a minimal product-like object for retrieve()."""
    product = MagicMock()
    product.product_id = product_id
    product.name = name
    product.description = f"{name} desc"
    product.image = None
    product.is_recurring = True
    product.metadata = {}
    product.tax_category = "saas"
    product.addons = addons or []
    price = MagicMock()
    price.type = price_type
    price.currency = "usd"
    price.price = 999
    price.fixed_price = None
    price.payment_frequency_interval = "month"
    price.subscription_period_interval = "month"
    price.meters = None
    product.price = price
    return product


def _make_addon(addon_id: str, name: str):
    """Build a minimal addon-like object for retrieve()."""
    addon = MagicMock()
    addon.id = addon_id
    addon.name = name
    addon.description = f"{name} addon"
    addon.image = None
    addon.price = 199
    addon.currency = "usd"
    addon.tax_category = "digital_products"
    return addon


def _make_meter(meter_id: str, name: str, event_name: str = "api_call"):
    """Build a minimal meter-like object for retrieve()."""
    meter = MagicMock()
    meter.id = meter_id
    meter.name = name
    meter.description = f"{name} meter"
    meter.event_name = event_name
    meter.measurement_unit = "request"
    agg = MagicMock()
    agg.type = "count"
    agg.key = "count"
    meter.aggregation = agg
    return meter


@pytest.mark.asyncio
async def test_get_plans_fetches_four_plans_with_plan_type_and_badge():
    """get_plans returns 4 plans in order with plan_type, show_discounted_badge (annual), includes_encryption."""
    products = [
        _make_product("prod_m_core_ai", "Monthly Core+AI", addons=[]),
        _make_product("prod_m_core_ai_enc", "Monthly Core+AI+Encryption", addons=[]),
        _make_product("prod_a_core_ai", "Annual Core+AI", addons=[]),
        _make_product("prod_a_core_ai_enc", "Annual Core+AI+Encryption", addons=[]),
    ]
    mock_client = MagicMock()
    mock_client.products.retrieve.side_effect = products

    with (
        patch("service.billing.is_plans_configured", return_value=True),
        patch("service.billing._plans_cache", None),
        patch("service.billing._plans_cache_time", 0.0),
        patch("service.billing._get_dodo_client", return_value=mock_client),
        patch("service.billing.settings") as mock_settings,
    ):
        mock_settings.DODO_PAYMENTS_MONTHLY_CORE_AI = "prod_m_core_ai"
        mock_settings.DODO_PAYMENTS_MONTHLY_CORE_AI_ENCRYPTION = "prod_m_core_ai_enc"
        mock_settings.DODO_PAYMENTS_ANNUAL_CORE_AI = "prod_a_core_ai"
        mock_settings.DODO_PAYMENTS_ANNUAL_CORE_AI_ENCRYPTION = "prod_a_core_ai_enc"
        plans = await billing.get_plans()

    assert len(plans) == 4
    assert plans[0]["product_id"] == "prod_m_core_ai"
    assert plans[0]["plan_type"] == "monthly_core_ai"
    assert plans[0]["show_discounted_badge"] is False
    assert plans[0]["includes_encryption"] is False

    assert plans[1]["plan_type"] == "monthly_core_ai_encryption"
    assert plans[1]["includes_encryption"] is True

    assert plans[2]["plan_type"] == "annual_core_ai"
    assert plans[2]["show_discounted_badge"] is True
    assert plans[2]["includes_encryption"] is False

    assert plans[3]["plan_type"] == "annual_core_ai_encryption"
    assert plans[3]["show_discounted_badge"] is True
    assert plans[3]["includes_encryption"] is True

    assert mock_client.products.retrieve.call_count == 4
    mock_client.products.retrieve.assert_any_call("prod_m_core_ai")
    mock_client.products.retrieve.assert_any_call("prod_m_core_ai_enc")
    mock_client.products.retrieve.assert_any_call("prod_a_core_ai")
    mock_client.products.retrieve.assert_any_call("prod_a_core_ai_enc")


@pytest.mark.asyncio
async def test_get_plans_empty_when_no_slots_configured():
    """get_plans returns empty list when no plan product IDs are configured (_get_plan_slots empty)."""
    with (
        patch("service.billing.is_plans_configured", return_value=True),
        patch("service.billing._plans_cache", None),
        patch("service.billing._plans_cache_time", 0.0),
        patch("service.billing._get_plan_slots", return_value=[]),
    ):
        plans = await billing.get_plans()

    assert plans == []


@pytest.mark.asyncio
async def test_create_checkout_session_single_product_cart():
    """create_checkout_session sends single product in product_cart (no addons)."""
    mock_checkout_resp = MagicMock()
    mock_checkout_resp.session_id = "sess_xyz"
    mock_checkout_resp.checkout_url = "https://checkout.example.com/xyz"

    mock_client = MagicMock()
    mock_client.checkout_sessions.create.return_value = mock_checkout_resp

    with (
        patch("service.billing.is_checkout_configured", return_value=True),
        patch("service.billing.get_allowed_product_ids", return_value=[]),
        patch("service.billing._get_dodo_client", return_value=mock_client),
    ):
        result = await billing.create_checkout_session(
            user_id=1,
            product_id="prod_annual_core_ai_enc",
            return_url="https://app.example.com/success",
        )

    assert result["session_id"] == "sess_xyz"
    assert result["checkout_url"] == "https://checkout.example.com/xyz"
    mock_client.checkout_sessions.create.assert_called_once()
    call_kwargs = mock_client.checkout_sessions.create.call_args[1]
    product_cart = call_kwargs["product_cart"]
    assert len(product_cart) == 1
    assert product_cart[0]["product_id"] == "prod_annual_core_ai_enc"
    assert product_cart[0]["quantity"] == 1
    assert "addons" not in product_cart[0]
    assert call_kwargs["metadata"] == {"user_id": "1"}
    assert call_kwargs["return_url"] == "https://app.example.com/success"


@pytest.mark.asyncio
async def test_create_checkout_session_rejects_disallowed_product_id():
    """create_checkout_session raises ValueError when product_id is not one of the 4 allowed plans."""
    with (
        patch("service.billing.is_checkout_configured", return_value=True),
        patch(
            "service.billing.get_allowed_product_ids",
            return_value=["prod_m_ca", "prod_m_cae", "prod_a_ca", "prod_a_cae"],
        ),
    ):
        with pytest.raises(ValueError, match="not an allowed plan"):
            await billing.create_checkout_session(user_id=1, product_id="prod_unknown")


@pytest.mark.asyncio
async def test_handle_webhook_subscription_event_sets_product_id(
    test_db_session: AsyncSession,
    sample_user_data: dict,
):
    """Subscription webhook event with product_id in payload sets PlanSubscription.product_id."""
    from auth.password import get_password_hash
    from service.user import create_user

    data = sample_user_data.copy()
    data["password_hash"] = get_password_hash(data.pop("password"))
    user = await create_user(test_db_session, data)
    await test_db_session.commit()

    event = {
        "type": "subscription.created",
        "data": {
            "id": "sub_dodo_xyz",
            "customer_id": "cust_abc",
            "metadata": {"user_id": str(user.id)},
            "product_id": "prod_monthly_core_ai_enc",
        },
    }
    await billing.handle_webhook_event(test_db_session, event)
    await test_db_session.commit()

    result = await test_db_session.execute(
        select(PlanSubscription).where(PlanSubscription.dodo_subscription_id == "sub_dodo_xyz")
    )
    row = result.scalar_one_or_none()
    assert row is not None
    assert row.product_id == "prod_monthly_core_ai_enc"
    assert row.user_id == user.id


def _make_dodo_subscription(
    subscription_id: str = "sub_123",
    status: str = "active",
    metadata: dict | None = None,
    customer_id: str = "cust_abc",
    product_id: str = "prod_monthly_core_ai",
):
    """Build a minimal Dodo subscription-like object for subscriptions.retrieve()."""
    sub = MagicMock()
    sub.subscription_id = subscription_id
    sub.status = status
    sub.metadata = metadata or {}
    sub.customer_id = customer_id
    sub.customer = MagicMock()
    sub.customer.customer_id = customer_id
    sub.customer.id = customer_id
    sub.product_id = product_id
    sub.next_billing_date = None
    return sub


@pytest.mark.asyncio
async def test_complete_subscription_creates_plan_subscription(
    test_db_session: AsyncSession,
    sample_user_data: dict,
):
    """complete_subscription creates PlanSubscription when Dodo returns matching subscription and metadata.user_id."""
    from auth.password import get_password_hash
    from service.user import create_user

    data = sample_user_data.copy()
    data["password_hash"] = get_password_hash(data.pop("password"))
    user = await create_user(test_db_session, data)
    await test_db_session.commit()

    mock_sub = _make_dodo_subscription(
        subscription_id="sub_new_123",
        status="active",
        metadata={"user_id": str(user.id)},
        customer_id="cust_dodo_1",
        product_id="prod_monthly_core_ai_enc",
    )
    mock_client = MagicMock()
    mock_client.subscriptions.retrieve.return_value = mock_sub

    with (
        patch("service.billing.is_checkout_configured", return_value=True),
        patch("service.billing._get_dodo_client", return_value=mock_client),
    ):
        await billing.complete_subscription(
            db=test_db_session,
            user_id=user.id,
            subscription_id="sub_new_123",
            status="active",
        )
    await test_db_session.commit()

    result = await test_db_session.execute(
        select(PlanSubscription).where(PlanSubscription.dodo_subscription_id == "sub_new_123")
    )
    row = result.scalar_one_or_none()
    assert row is not None
    assert row.user_id == user.id
    assert row.status == "active"
    assert row.dodo_customer_id == "cust_dodo_1"
    assert row.product_id == "prod_monthly_core_ai_enc"
    mock_client.subscriptions.retrieve.assert_called_once_with("sub_new_123")


@pytest.mark.asyncio
async def test_complete_subscription_updates_existing_plan_subscription(
    test_db_session: AsyncSession,
    sample_user_data: dict,
):
    """complete_subscription updates existing PlanSubscription when row already exists."""
    from auth.password import get_password_hash
    from service.user import create_user

    data = sample_user_data.copy()
    data["password_hash"] = get_password_hash(data.pop("password"))
    user = await create_user(test_db_session, data)
    await test_db_session.commit()

    existing = PlanSubscription(
        user_id=user.id,
        dodo_subscription_id="sub_existing",
        dodo_customer_id="cust_old",
        status="pending",
        product_id=None,
    )
    test_db_session.add(existing)
    await test_db_session.commit()

    mock_sub = _make_dodo_subscription(
        subscription_id="sub_existing",
        status="active",
        metadata={"user_id": str(user.id)},
        customer_id="cust_new",
        product_id="prod_annual_core_ai",
    )
    mock_client = MagicMock()
    mock_client.subscriptions.retrieve.return_value = mock_sub

    with (
        patch("service.billing.is_checkout_configured", return_value=True),
        patch("service.billing._get_dodo_client", return_value=mock_client),
    ):
        await billing.complete_subscription(
            db=test_db_session,
            user_id=user.id,
            subscription_id="sub_existing",
            status="active",
        )
    await test_db_session.commit()

    result = await test_db_session.execute(
        select(PlanSubscription).where(PlanSubscription.dodo_subscription_id == "sub_existing")
    )
    row = result.scalar_one_or_none()
    assert row is not None
    assert row.user_id == user.id
    assert row.status == "active"
    assert row.dodo_customer_id == "cust_new"
    assert row.product_id == "prod_annual_core_ai"


@pytest.mark.asyncio
async def test_complete_subscription_not_found_raises():
    """complete_subscription raises BillingCompleteError 404 when Dodo returns not found."""
    class DodoNotFoundError(Exception):
        pass
    DodoNotFoundError.__module__ = "dodopayments.errors"
    DodoNotFoundError.__name__ = "NotFoundError"

    mock_client = MagicMock()
    mock_client.subscriptions.retrieve.side_effect = DodoNotFoundError("Subscription not found")

    with (
        patch("service.billing.is_checkout_configured", return_value=True),
        patch("service.billing._get_dodo_client", return_value=mock_client),
    ):
        with pytest.raises(billing.BillingCompleteError) as exc_info:
            await billing.complete_subscription(
                db=MagicMock(),
                user_id=1,
                subscription_id="sub_nonexistent",
                status="active",
            )
    assert exc_info.value.status_code == 404
    assert "not found" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_complete_subscription_status_mismatch_raises(
    test_db_session: AsyncSession,
):
    """complete_subscription raises BillingCompleteError 400 when Dodo status does not match request."""
    mock_sub = _make_dodo_subscription(
        subscription_id="sub_123",
        status="pending",
        metadata={"user_id": "1"},
    )
    mock_client = MagicMock()
    mock_client.subscriptions.retrieve.return_value = mock_sub

    with (
        patch("service.billing.is_checkout_configured", return_value=True),
        patch("service.billing._get_dodo_client", return_value=mock_client),
    ):
        with pytest.raises(billing.BillingCompleteError) as exc_info:
            await billing.complete_subscription(
                db=test_db_session,
                user_id=1,
                subscription_id="sub_123",
                status="active",
            )
    assert exc_info.value.status_code == 400
    assert "status" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_complete_subscription_wrong_user_raises_403(
    test_db_session: AsyncSession,
):
    """complete_subscription raises BillingCompleteError 403 when metadata.user_id != current user."""
    mock_sub = _make_dodo_subscription(
        subscription_id="sub_123",
        status="active",
        metadata={"user_id": "999"},
        customer_id="cust_1",
    )
    mock_client = MagicMock()
    mock_client.subscriptions.retrieve.return_value = mock_sub

    with (
        patch("service.billing.is_checkout_configured", return_value=True),
        patch("service.billing._get_dodo_client", return_value=mock_client),
    ):
        with pytest.raises(billing.BillingCompleteError) as exc_info:
            await billing.complete_subscription(
                db=test_db_session,
                user_id=1,
                subscription_id="sub_123",
                status="active",
            )
    assert exc_info.value.status_code == 403
    assert "does not belong" in exc_info.value.detail.lower()
