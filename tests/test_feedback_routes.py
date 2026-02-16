"""Tests for feedback routes: POST (public), GET/DELETE (superuser)."""

import pytest
from fastapi import status

from auth.password import get_password_hash
from service.feedback import create_feedback
from service.user import create_user, grant_superuser


def _login(test_client, email: str, password: str) -> str:
    """Log in and return access token."""
    r = test_client.post(
        "/api/auth/login-json",
        json={"email": email, "password": password},
    )
    assert r.status_code == status.HTTP_200_OK
    return r.json()["access_token"]


@pytest.mark.asyncio
async def test_post_feedback_without_auth_succeeds(
    test_client,
    test_db_session,
):
    """POST /feedback without auth returns 201 and stores feedback."""
    response = test_client.post(
        "/api/feedback",
        json={"content": "Great feature!"},
    )
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data["content"] == "Great feature!"
    assert "id" in data
    assert "created_at" in data
    assert data.get("context") is None


@pytest.mark.asyncio
async def test_post_feedback_with_context(
    test_client,
    test_db_session,
):
    """POST /feedback accepts optional context."""
    response = test_client.post(
        "/api/feedback",
        json={
            "content": "Bug report",
            "context": {"page": "settings", "version": "1.0.0"},
        },
    )
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data["content"] == "Bug report"
    assert data["context"] == {"page": "settings", "version": "1.0.0"}


@pytest.mark.asyncio
async def test_post_feedback_missing_content_returns_422(test_client):
    """POST /feedback with missing content returns 422."""
    response = test_client.post(
        "/api/feedback",
        json={},
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


@pytest.mark.asyncio
async def test_post_feedback_empty_content_returns_422(test_client):
    """POST /feedback with empty content returns 422."""
    response = test_client.post(
        "/api/feedback",
        json={"content": ""},
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


@pytest.mark.asyncio
async def test_get_feedback_without_auth_returns_401(test_client):
    """GET /feedback without auth returns 401."""
    response = test_client.get("/api/feedback")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_get_feedback_as_non_superuser_returns_403(
    test_client,
    test_db_session,
    sample_user_data: dict,
):
    """GET /feedback as non-superuser returns 403."""
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    await create_user(test_db_session, user_data)
    await test_db_session.commit()
    token = _login(test_client, sample_user_data["email"], sample_user_data["password"])

    response = test_client.get(
        "/api/feedback",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.asyncio
async def test_get_feedback_as_superuser_returns_list(
    test_client,
    test_db_session,
    sample_user_data: dict,
):
    """GET /feedback as superuser returns 200 and list of feedback."""
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

    feedback = await create_feedback(test_db_session, "Test feedback", {"source": "test"})
    await test_db_session.commit()

    admin_token = _login(test_client, "admin@example.com", "adminpass123")
    response = test_client.get(
        "/api/feedback",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    found = next((f for f in data if f["id"] == feedback.id), None)
    assert found is not None
    assert found["content"] == "Test feedback"
    assert found["context"] == {"source": "test"}


@pytest.mark.asyncio
async def test_delete_feedback_without_auth_returns_401(test_client):
    """DELETE /feedback/{id} without auth returns 401."""
    response = test_client.delete("/api/feedback/1")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_delete_feedback_as_non_superuser_returns_403(
    test_client,
    test_db_session,
    sample_user_data: dict,
):
    """DELETE /feedback/{id} as non-superuser returns 403."""
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    await create_user(test_db_session, user_data)
    await test_db_session.commit()

    feedback = await create_feedback(test_db_session, "To delete")
    await test_db_session.commit()

    token = _login(test_client, sample_user_data["email"], sample_user_data["password"])
    response = test_client.delete(
        f"/api/feedback/{feedback.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.asyncio
async def test_delete_feedback_as_superuser_returns_204(
    test_client,
    test_db_session,
    sample_user_data: dict,
):
    """DELETE /feedback/{id} as superuser returns 204."""
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

    feedback = await create_feedback(test_db_session, "To delete")
    await test_db_session.commit()

    admin_token = _login(test_client, "admin@example.com", "adminpass123")
    response = test_client.delete(
        f"/api/feedback/{feedback.id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == status.HTTP_204_NO_CONTENT


@pytest.mark.asyncio
async def test_delete_feedback_nonexistent_returns_404(
    test_client,
    test_db_session,
    sample_user_data: dict,
):
    """DELETE /feedback/{id} for non-existent feedback returns 404."""
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
    response = test_client.delete(
        "/api/feedback/99999",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == status.HTTP_404_NOT_FOUND
