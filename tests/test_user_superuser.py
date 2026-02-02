"""Tests for superuser grant/revoke endpoints (POST/DELETE /users/{id}/superuser)."""

import pytest
from fastapi import status

from auth.password import get_password_hash
from service.user import create_user, grant_superuser


def _login(test_client, email: str, password: str) -> str:
    r = test_client.post(
        "/auth/login-json",
        json={"email": email, "password": password},
    )
    assert r.status_code == status.HTTP_200_OK
    return r.json()["access_token"]


@pytest.mark.asyncio
async def test_grant_superuser_requires_superuser(
    test_client,
    test_db_session,
    sample_user_data: dict,
):
    """POST /users/{id}/superuser returns 403 when caller is not a superuser."""
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user = await create_user(test_db_session, user_data)
    await test_db_session.commit()
    token = _login(test_client, sample_user_data["email"], sample_user_data["password"])
    response = test_client.post(
        f"/users/{user.id}/superuser",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.asyncio
async def test_grant_and_revoke_superuser(
    test_client,
    test_db_session,
    sample_user_data: dict,
):
    """Superuser can grant then revoke superuser privilege for another user."""
    # Create superuser (admin)
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

    # Create regular user
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user = await create_user(test_db_session, user_data)
    await test_db_session.commit()

    # Grant superuser to user
    response = test_client.post(
        f"/users/{user.id}/superuser",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["is_superuser"] is True

    # Revoke superuser
    response = test_client.delete(
        f"/users/{user.id}/superuser",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["is_superuser"] is False
