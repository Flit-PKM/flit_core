"""Admin stats, prune dry-run, last_login, feedback responses, access list/revoke, logout."""

from datetime import timedelta, timezone

import pytest
from fastapi import status
from sqlalchemy import select

from auth.password import get_password_hash
from models.feedback import Feedback
from models.user import User
from service.user import create_user, grant_superuser


def _login_json(test_client, email: str, password: str) -> str:
    r = test_client.post(
        "/api/auth/login-json",
        json={"email": email, "password": password},
    )
    assert r.status_code == status.HTTP_200_OK
    return r.json()["access_token"]


@pytest.mark.asyncio
async def test_last_login_set_after_login_json(test_client, test_db_session):
    user_data = {
        "username": "lluser",
        "email": "lluser@example.com",
        "password_hash": get_password_hash("password123"),
        "is_verified": False,
    }
    u = await create_user(test_db_session, user_data)
    await test_db_session.commit()
    r = await test_db_session.execute(select(User).where(User.id == u.id))
    row = r.scalar_one()
    assert row.last_login is not None
    assert row.last_login.tzinfo is None
    at_create = row.last_login

    _login_json(test_client, "lluser@example.com", "password123")

    r2 = await test_db_session.execute(select(User).where(User.id == u.id))
    row2 = r2.scalar_one()
    assert row2.last_login is not None
    assert row2.last_login.tzinfo is None
    assert row2.last_login >= at_create


@pytest.mark.asyncio
async def test_admin_stats_ok_for_superuser(test_client, test_db_session):
    admin_data = {
        "username": "admstats",
        "email": "admstats@example.com",
        "password_hash": get_password_hash("adminpass123"),
        "is_verified": True,
    }
    admin = await create_user(test_db_session, admin_data)
    await grant_superuser(test_db_session, admin.id)
    await test_db_session.commit()
    token = _login_json(test_client, "admstats@example.com", "adminpass123")
    r = test_client.get(
        "/api/admin/stats",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == status.HTTP_200_OK
    data = r.json()
    assert "users" in data and "feedback" in data
    assert data["users"]["total"] >= 1
    assert "active_login_last_30d" in data["users"]
    assert "with_login" not in data["users"]
    assert "never_logged_in" not in data["users"]
    assert "billing" in data


@pytest.mark.asyncio
async def test_prune_dry_run_matched_stale_unverified(test_client, test_db_session):
    admin_data = {
        "username": "pruneadmin",
        "email": "pruneadmin@example.com",
        "password_hash": get_password_hash("adminpass123"),
        "is_verified": True,
    }
    admin = await create_user(test_db_session, admin_data)
    await grant_superuser(test_db_session, admin.id)
    stale_data = {
        "username": "staleu",
        "email": "staleu@example.com",
        "password_hash": get_password_hash("password123"),
        "is_verified": False,
    }
    stale = await create_user(test_db_session, stale_data)
    from datetime import datetime

    old = (datetime.now(timezone.utc) - timedelta(days=90)).replace(tzinfo=None)
    stale.created_at = old
    stale.last_login = old
    await test_db_session.commit()

    token = _login_json(test_client, "pruneadmin@example.com", "adminpass123")
    r = test_client.post(
        "/api/users/prune",
        headers={"Authorization": f"Bearer {token}"},
        json={"inactive_for_days": 30, "dry_run": True},
    )
    assert r.status_code == status.HTTP_200_OK
    body = r.json()
    assert body["deleted_count"] == 0
    assert body["matched_count"] >= 1
    assert stale.id in body["sample_user_ids"]


@pytest.mark.asyncio
async def test_feedback_responses_superuser(test_client, test_db_session):
    admin_data = {
        "username": "fbadmin",
        "email": "fbadmin@example.com",
        "password_hash": get_password_hash("adminpass123"),
        "is_verified": True,
    }
    admin = await create_user(test_db_session, admin_data)
    await grant_superuser(test_db_session, admin.id)
    fb = Feedback(content="hello", context=None)
    test_db_session.add(fb)
    await test_db_session.commit()
    await test_db_session.refresh(fb)
    token = _login_json(test_client, "fbadmin@example.com", "adminpass123")

    cr = test_client.post(
        f"/api/feedback/{fb.id}/responses",
        headers={"Authorization": f"Bearer {token}"},
        json={"body": "Thanks for your note"},
    )
    assert cr.status_code == status.HTTP_201_CREATED
    lr = test_client.get(
        f"/api/feedback/{fb.id}/responses",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert lr.status_code == status.HTTP_200_OK
    assert len(lr.json()) == 1
    assert lr.json()[0]["body"] == "Thanks for your note"


@pytest.mark.asyncio
async def test_access_codes_list_and_revoke(test_client, test_db_session):
    admin_data = {
        "username": "acadmin",
        "email": "acadmin@example.com",
        "password_hash": get_password_hash("adminpass123"),
        "is_verified": True,
    }
    admin = await create_user(test_db_session, admin_data)
    await grant_superuser(test_db_session, admin.id)
    await test_db_session.commit()
    token = _login_json(test_client, "acadmin@example.com", "adminpass123")
    cr = test_client.get(
        "/api/access-codes/create?period_weeks=4",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert cr.status_code == status.HTTP_201_CREATED
    code = cr.json()["code"]
    lst = test_client.get(
        "/api/access-codes",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert lst.status_code == status.HTTP_200_OK
    assert any(row["code"] == code for row in lst.json())
    rv = test_client.post(
        f"/api/access-codes/{code}/revoke",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert rv.status_code == status.HTTP_200_OK
    assert rv.json()["revoked_at"] is not None


def test_logout_invalidates_token(test_client, test_db_session):
    """Sync-only HTTP calls so the shared AsyncSession stays on TestClient's loop."""
    import asyncio

    async def _setup():
        u = User(
            email="lgout@example.com",
            username="lgout",
            password_hash=get_password_hash("password123"),
            is_verified=True,
        )
        test_db_session.add(u)
        await test_db_session.flush()
        await test_db_session.commit()

    asyncio.get_event_loop().run_until_complete(_setup())
    r = test_client.post(
        "/api/auth/login-json",
        json={"email": "lgout@example.com", "password": "password123"},
    )
    assert r.status_code == status.HTTP_200_OK
    token = r.json()["access_token"]
    lo = test_client.post(
        "/api/auth/logout", headers={"Authorization": f"Bearer {token}"}
    )
    assert lo.status_code == status.HTTP_200_OK
    me = test_client.get("/api/user", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == status.HTTP_401_UNAUTHORIZED


def test_admin_stats_requires_superuser(test_client):
    r = test_client.get("/api/admin/stats")
    assert r.status_code in (
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
    )
