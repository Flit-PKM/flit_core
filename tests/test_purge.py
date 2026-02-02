"""Tests for purge: soft-deleted rows older than N weeks are hard-deleted."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from auth.password import get_password_hash
from models.connected_app import ConnectedApp
from models.note import Note
from models.user import User
from service.purge import purge_soft_deleted_older_than


@pytest_asyncio.fixture
async def purge_test_data(test_db_session: AsyncSession):
    """User, connected_app, and a note for purge tests."""
    user = User(
        username="purgeuser",
        email="purge@example.com",
        password_hash=get_password_hash("password123"),
        is_active=True,
        is_verified=False,
    )
    test_db_session.add(user)
    await test_db_session.flush()

    app = ConnectedApp(
        user_id=user.id,
        app_slug="flit",
        device_name="Test",
        platform="test",
        app_version="1.0",
    )
    test_db_session.add(app)
    await test_db_session.flush()

    await test_db_session.commit()
    return {"user": user, "connected_app": app}


@pytest.mark.asyncio
async def test_purge_removes_old_soft_deleted_note(
    test_db_session: AsyncSession,
    purge_test_data: dict,
):
    """Rows with is_deleted=True and updated_at older than N weeks are removed."""
    user = purge_test_data["user"]
    app = purge_test_data["connected_app"]

    note = Note(
        title="Old Deleted",
        content="Content",
        type="BASE",
        version=1,
        user_id=user.id,
        source_id=app.id,
        is_deleted=True,
    )
    test_db_session.add(note)
    await test_db_session.flush()
    note_id = note.id
    await test_db_session.commit()

    # Set updated_at to 8 weeks ago (older than default 6)
    eight_weeks_ago = (datetime.now(timezone.utc) - timedelta(weeks=8)).isoformat()
    await test_db_session.execute(
        text("UPDATE notes SET updated_at = :t WHERE id = :id"),
        {"t": eight_weeks_ago, "id": note_id},
    )
    await test_db_session.commit()

    counts = await purge_soft_deleted_older_than(test_db_session, weeks=6)
    assert counts.get("notes", 0) >= 1

    r = await test_db_session.execute(select(Note).where(Note.id == note_id))
    assert r.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_purge_leaves_recent_soft_deleted(
    test_db_session: AsyncSession,
    purge_test_data: dict,
):
    """Rows with is_deleted=True but updated_at within the window are not removed."""
    user = purge_test_data["user"]
    app = purge_test_data["connected_app"]

    note = Note(
        title="Recent Deleted",
        content="Content",
        type="BASE",
        version=1,
        user_id=user.id,
        source_id=app.id,
        is_deleted=True,
    )
    test_db_session.add(note)
    await test_db_session.flush()
    note_id = note.id
    await test_db_session.commit()

    # updated_at is "now" by default, so within 6 weeks
    counts = await purge_soft_deleted_older_than(test_db_session, weeks=6)
    # May purge 0 or 1 depending on whether our note's updated_at is considered old
    # We want to assert our note is still there: use a short window so "now" is inside
    r = await test_db_session.execute(select(Note).where(Note.id == note_id))
    assert r.scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_purge_leaves_non_deleted(
    test_db_session: AsyncSession,
    purge_test_data: dict,
):
    """Rows with is_deleted=False are never removed, even if updated_at is old."""
    user = purge_test_data["user"]
    app = purge_test_data["connected_app"]

    note = Note(
        title="Old But Not Deleted",
        content="Content",
        type="BASE",
        version=1,
        user_id=user.id,
        source_id=app.id,
        is_deleted=False,
    )
    test_db_session.add(note)
    await test_db_session.flush()
    note_id = note.id
    await test_db_session.commit()

    eight_weeks_ago = (datetime.now(timezone.utc) - timedelta(weeks=8)).isoformat()
    await test_db_session.execute(
        text("UPDATE notes SET updated_at = :t WHERE id = :id"),
        {"t": eight_weeks_ago, "id": note_id},
    )
    await test_db_session.commit()

    await purge_soft_deleted_older_than(test_db_session, weeks=6)

    r = await test_db_session.execute(select(Note).where(Note.id == note_id))
    assert r.scalar_one_or_none() is not None
