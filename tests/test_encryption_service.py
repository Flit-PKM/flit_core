"""Unit and integration tests for encryption at rest (notes and chunks)."""

import base64
import os
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models.plan_subscription import PlanSubscription
from models.user_encryption_key import UserEncryptionKey
from service.encryption import get_or_create_dek, user_has_encryption_plan
from service.user import create_user


@pytest.mark.asyncio
async def test_get_or_create_dek_returns_none_when_encryption_disabled(
    test_db_session: AsyncSession,
    sample_user_data: dict,
):
    """When ENCRYPTION_MASTER_KEY is not set, get_or_create_dek returns None."""
    from auth.password import get_password_hash
    sample_user_data = sample_user_data.copy()
    sample_user_data["password_hash"] = get_password_hash(
        sample_user_data.pop("password")
    )
    user = await create_user(test_db_session, sample_user_data)
    await test_db_session.commit()
    # Encryption is disabled by default in tests
    dek = await get_or_create_dek(test_db_session, user.id)
    assert dek is None


@pytest.mark.asyncio
async def test_get_or_create_dek_creates_and_returns_same_dek(
    test_db_session: AsyncSession,
    sample_user_data: dict,
    monkeypatch,
):
    """With encryption enabled and user has encryption plan, get_or_create_dek creates one row and returns same DEK on second call."""
    import config as config_module
    import service.encryption as enc_module
    key_b64 = base64.b64encode(os.urandom(32)).decode("utf-8")
    monkeypatch.setattr(config_module.settings, "ENCRYPTION_MASTER_KEY", key_b64)

    async def _user_has_plan(_session, _user_id):
        return True

    monkeypatch.setattr(enc_module, "user_has_encryption_plan", _user_has_plan)

    from auth.password import get_password_hash
    data = sample_user_data.copy()
    data["password_hash"] = get_password_hash(data.pop("password"))
    user = await create_user(test_db_session, data)
    await test_db_session.commit()

    dek1 = await get_or_create_dek(test_db_session, user.id)
    assert dek1 is not None
    assert len(dek1) == 32

    from sqlalchemy import select
    r = await test_db_session.execute(
        select(UserEncryptionKey).where(UserEncryptionKey.user_id == user.id)
    )
    row = r.scalar_one_or_none()
    assert row is not None
    assert row.encrypted_dek

    dek2 = await get_or_create_dek(test_db_session, user.id)
    assert dek2 == dek1


@pytest.mark.asyncio
async def test_user_has_encryption_plan_true_when_active_subscription_with_encryption_product(
    test_db_session: AsyncSession,
    sample_user_data: dict,
    monkeypatch,
):
    """user_has_encryption_plan returns True when user has active PlanSubscription with encryption product_id."""
    from auth.password import get_password_hash
    data = sample_user_data.copy()
    data["password_hash"] = get_password_hash(data.pop("password"))
    user = await create_user(test_db_session, data)
    sub = PlanSubscription(
        user_id=user.id,
        dodo_subscription_id="sub_enc",
        dodo_customer_id="cust_1",
        status="active",
        product_id="prod_monthly_enc",
    )
    test_db_session.add(sub)
    await test_db_session.commit()

    import service.encryption as enc_module
    monkeypatch.setattr(
        enc_module,
        "_encryption_product_ids",
        lambda: {"prod_monthly_enc", "prod_annual_enc"},
    )

    result = await user_has_encryption_plan(test_db_session, user.id)
    assert result is True


@pytest.mark.asyncio
async def test_user_has_encryption_plan_false_when_no_subscription(
    test_db_session: AsyncSession,
    sample_user_data: dict,
):
    """user_has_encryption_plan returns False when user has no PlanSubscription."""
    from auth.password import get_password_hash
    data = sample_user_data.copy()
    data["password_hash"] = get_password_hash(data.pop("password"))
    user = await create_user(test_db_session, data)
    await test_db_session.commit()

    result = await user_has_encryption_plan(test_db_session, user.id)
    assert result is False


@pytest.mark.asyncio
async def test_user_has_encryption_plan_false_when_product_id_not_encryption(
    test_db_session: AsyncSession,
    sample_user_data: dict,
    monkeypatch,
):
    """user_has_encryption_plan returns False when product_id is not an encryption plan."""
    from auth.password import get_password_hash
    data = sample_user_data.copy()
    data["password_hash"] = get_password_hash(data.pop("password"))
    user = await create_user(test_db_session, data)
    sub = PlanSubscription(
        user_id=user.id,
        dodo_subscription_id="sub_core",
        dodo_customer_id="cust_1",
        status="active",
        product_id="prod_monthly_core_ai",
    )
    test_db_session.add(sub)
    await test_db_session.commit()

    import service.encryption as enc_module
    monkeypatch.setattr(
        enc_module,
        "_encryption_product_ids",
        lambda: {"prod_monthly_enc", "prod_annual_enc"},
    )

    result = await user_has_encryption_plan(test_db_session, user.id)
    assert result is False
