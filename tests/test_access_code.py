"""Tests for access code create/activate routes and entitlement (sync/encryption gate)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import status

from auth.password import get_password_hash
from service.access_code import activate_code, create_access_code
from service.billing import require_active_subscription
from service.encryption import user_has_encryption_plan
from service.user import create_user, grant_superuser


def _login(test_client, email: str, password: str) -> str:
    r = test_client.post(
        "/api/auth/login-json",
        json={"email": email, "password": password},
    )
    assert r.status_code == status.HTTP_200_OK
    return r.json()["access_token"]


@pytest.mark.asyncio
async def test_create_code_requires_superuser(
    test_client,
    test_db_session,
    sample_user_data: dict,
):
    """GET /access-codes/create returns 403 when caller is not a superuser."""
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    await create_user(test_db_session, user_data)
    await test_db_session.commit()
    token = _login(test_client, sample_user_data["email"], sample_user_data["password"])
    response = test_client.get(
        "/api/access-codes/create",
        params={"period_weeks": 4, "includes_encryption": False},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.asyncio
async def test_create_code_validation_period_weeks(
    test_client,
    test_db_session,
    sample_user_data: dict,
):
    """GET /access-codes/create returns 400 when period_weeks is out of range."""
    admin_data = {
        "username": "admin",
        "email": "admin@example.com",
        "password_hash": get_password_hash("adminpass123"),
        "is_verified": False,
    }
    admin = await create_user(test_db_session, admin_data)
    await test_db_session.commit()
    await grant_superuser(test_db_session, admin.id)
    await test_db_session.commit()
    token = _login(test_client, "admin@example.com", "adminpass123")
    for bad_weeks in (0, -1, 53, 100):
        response = test_client.get(
            "/api/access-codes/create",
            params={"period_weeks": bad_weeks, "includes_encryption": False},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, f"period_weeks={bad_weeks}"


@pytest.mark.asyncio
async def test_create_code_success(
    test_client,
    test_db_session,
    sample_user_data: dict,
):
    """Superuser can create a code; response has code, period_weeks, includes_encryption."""
    admin_data = {
        "username": "admin",
        "email": "admin@example.com",
        "password_hash": get_password_hash("adminpass123"),
        "is_verified": False,
    }
    admin = await create_user(test_db_session, admin_data)
    await test_db_session.commit()
    await grant_superuser(test_db_session, admin.id)
    await test_db_session.commit()
    token = _login(test_client, "admin@example.com", "adminpass123")
    response = test_client.get(
        "/api/access-codes/create",
        params={"period_weeks": 2, "includes_encryption": True},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert "code" in data
    assert len(data["code"]) == 8
    assert data["period_weeks"] == 2
    assert data["includes_encryption"] is True


@pytest.mark.asyncio
async def test_activate_success(
    test_client,
    test_db_session,
    sample_user_data: dict,
):
    """User can activate a code; response has expires_at and includes_encryption."""
    admin_data = {
        "username": "admin",
        "email": "admin@example.com",
        "password_hash": get_password_hash("adminpass123"),
        "is_verified": False,
    }
    admin = await create_user(test_db_session, admin_data)
    await test_db_session.commit()
    await grant_superuser(test_db_session, admin.id)
    await test_db_session.commit()
    admin_token = _login(test_client, "admin@example.com", "adminpass123")
    create_resp = test_client.get(
        "/api/access-codes/create",
        params={"period_weeks": 4, "includes_encryption": False},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert create_resp.status_code == status.HTTP_201_CREATED
    code = create_resp.json()["code"]

    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    await create_user(test_db_session, user_data)
    await test_db_session.commit()
    user_token = _login(test_client, sample_user_data["email"], sample_user_data["password"])

    response = test_client.post(
        "/api/access-codes/activate",
        json={"code": code},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert "expires_at" in data
    assert data["includes_encryption"] is False


@pytest.mark.asyncio
async def test_activate_invalid_code(
    test_client,
    test_db_session,
    sample_user_data: dict,
):
    """POST /access-codes/activate with unknown code returns 400."""
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    await create_user(test_db_session, user_data)
    await test_db_session.commit()
    token = _login(test_client, sample_user_data["email"], sample_user_data["password"])
    response = test_client.post(
        "/api/access-codes/activate",
        json={"code": "INVALID1"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.asyncio
async def test_activate_already_used(
    test_client,
    test_db_session,
    sample_user_data: dict,
):
    """Activating the same code twice returns 409 the second time."""
    admin_data = {
        "username": "admin",
        "email": "admin@example.com",
        "password_hash": get_password_hash("adminpass123"),
        "is_verified": False,
    }
    admin = await create_user(test_db_session, admin_data)
    await test_db_session.commit()
    await grant_superuser(test_db_session, admin.id)
    await test_db_session.commit()
    admin_token = _login(test_client, "admin@example.com", "adminpass123")
    create_resp = test_client.get(
        "/api/access-codes/create",
        params={"period_weeks": 2, "includes_encryption": False},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    code = create_resp.json()["code"]

    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user = await create_user(test_db_session, user_data)
    await test_db_session.commit()
    user_token = _login(test_client, sample_user_data["email"], sample_user_data["password"])

    first = test_client.post(
        "/api/access-codes/activate",
        json={"code": code},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert first.status_code == status.HTTP_200_OK

    second = test_client.post(
        "/api/access-codes/activate",
        json={"code": code},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert second.status_code == status.HTTP_409_CONFLICT


@pytest.mark.asyncio
async def test_require_active_subscription_allows_access_grant(
    test_db_session,
    sample_user_data: dict,
):
    """When billing is configured, user with no plan but with non-expired access grant passes require_active_subscription."""
    from auth.password import get_password_hash

    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user = await create_user(test_db_session, user_data)
    await test_db_session.commit()

    admin_data = {
        "username": "admin",
        "email": "admin@example.com",
        "password_hash": get_password_hash("adminpass123"),
        "is_verified": False,
    }
    admin = await create_user(test_db_session, admin_data)
    await test_db_session.commit()

    access_code = await create_access_code(
        db=test_db_session,
        period_weeks=4,
        includes_encryption=False,
        created_by=admin.id,
    )
    await test_db_session.commit()
    await activate_code(db=test_db_session, code=access_code.code, user_id=user.id)
    await test_db_session.commit()

    with patch("service.billing.is_billing_configured", return_value=True):
        # Should not raise: user has access grant, no plan
        await require_active_subscription(test_db_session, user.id)


@pytest.mark.asyncio
async def test_user_has_encryption_plan_true_with_encryption_grant(
    test_db_session,
    sample_user_data: dict,
):
    """user_has_encryption_plan returns True when user has non-expired access grant with includes_encryption."""
    from auth.password import get_password_hash

    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user = await create_user(test_db_session, user_data)
    await test_db_session.commit()

    admin_data = {
        "username": "admin",
        "email": "admin@example.com",
        "password_hash": get_password_hash("adminpass123"),
        "is_verified": False,
    }
    admin = await create_user(test_db_session, admin_data)
    await test_db_session.commit()

    access_code = await create_access_code(
        db=test_db_session,
        period_weeks=4,
        includes_encryption=True,
        created_by=admin.id,
    )
    await test_db_session.commit()
    await activate_code(db=test_db_session, code=access_code.code, user_id=user.id)
    await test_db_session.commit()

    result = await user_has_encryption_plan(test_db_session, user.id)
    assert result is True


@pytest.mark.asyncio
async def test_get_user_includes_entitlement_active_and_access_grant(
    test_client,
    test_db_session,
    sample_user_data: dict,
):
    """GET /user returns entitlement_active and access_grant when user has an active access code."""
    from auth.password import get_password_hash

    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user = await create_user(test_db_session, user_data)
    await test_db_session.commit()

    admin_data = {
        "username": "admin",
        "email": "admin@example.com",
        "password_hash": get_password_hash("adminpass123"),
        "is_verified": False,
    }
    admin = await create_user(test_db_session, admin_data)
    await test_db_session.commit()

    access_code = await create_access_code(
        db=test_db_session,
        period_weeks=2,
        includes_encryption=True,
        created_by=admin.id,
    )
    await test_db_session.commit()
    await activate_code(db=test_db_session, code=access_code.code, user_id=user.id)
    await test_db_session.commit()

    token = _login(test_client, sample_user_data["email"], sample_user_data["password"])
    response = test_client.get("/api/user/", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["entitlement_active"] is True
    assert data["access_grant"] is not None
    assert "expires_at" in data["access_grant"]
    assert data["access_grant"]["includes_encryption"] is True
