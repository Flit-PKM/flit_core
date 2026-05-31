"""Tests for internal note state_hash and efficient updates."""

import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.password import get_password_hash
from models.notesearch import NoteSearch
from schemas.note import NoteCreate, NoteUpdate
from service.note import create_note, update_note
from service.note_state_hash import body_hash, compute_state_hash
from service.user import create_user


def _login(test_client, email: str, password: str) -> str:
    r = test_client.post(
        "/api/auth/login-json",
        json={"email": email, "password": password},
    )
    assert r.status_code == status.HTTP_200_OK
    return r.json()["access_token"]


def test_compute_state_hash_and_body_hash():
    h1 = compute_state_hash(title="A", content="B", pinned=False, color="")
    h2 = compute_state_hash(title="A", content="B", pinned=True, color="")
    assert h1 != h2
    assert body_hash(title="A", content="B") == body_hash(title="A", content="B")
    assert body_hash(title="A", content="B") != body_hash(title="A", content="C")


@pytest.mark.asyncio
async def test_update_note_noop_skips_version_and_notesearch(
    test_db_session: AsyncSession,
    sample_user_data: dict,
):
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user = await create_user(test_db_session, user_data)
    await test_db_session.commit()

    note = await create_note(
        test_db_session,
        NoteCreate(user_id=user.id, title="T", content="C", type="BASE"),
    )
    await test_db_session.commit()
    version_before = note.version

    result = await test_db_session.execute(
        select(NoteSearch).where(NoteSearch.note_id == note.id)
    )
    search_before = result.scalar_one().content

    updated = await update_note(
        test_db_session,
        note.id,
        NoteUpdate(title="T", content="C"),
    )
    await test_db_session.commit()

    assert updated.version == version_before
    result = await test_db_session.execute(
        select(NoteSearch).where(NoteSearch.note_id == note.id)
    )
    assert result.scalar_one().content == search_before


@pytest.mark.asyncio
async def test_update_note_pinned_only_bumps_version_not_notesearch(
    test_db_session: AsyncSession,
    sample_user_data: dict,
):
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user = await create_user(test_db_session, user_data)
    await test_db_session.commit()

    note = await create_note(
        test_db_session,
        NoteCreate(
            user_id=user.id,
            title="T",
            content="C",
            type="BASE",
            pinned=False,
            color="",
        ),
    )
    await test_db_session.commit()

    result = await test_db_session.execute(
        select(NoteSearch).where(NoteSearch.note_id == note.id)
    )
    search_before = result.scalar_one().content

    updated = await update_note(
        test_db_session, note.id, NoteUpdate(pinned=True)
    )
    await test_db_session.commit()

    assert updated.version == 2
    assert updated.pinned is True
    result = await test_db_session.execute(
        select(NoteSearch).where(NoteSearch.note_id == note.id)
    )
    assert result.scalar_one().content == search_before


@pytest.mark.asyncio
async def test_state_hash_not_in_api_response(
    test_client,
    test_db_session: AsyncSession,
    sample_user_data: dict,
):
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    await create_user(test_db_session, user_data)
    await test_db_session.commit()

    token = _login(test_client, sample_user_data["email"], sample_user_data["password"])
    headers = {"Authorization": f"Bearer {token}"}

    r = test_client.post(
        "/api/notes",
        json={"title": "API", "content": "Body", "type": "BASE"},
        headers=headers,
    )
    assert r.status_code == status.HTTP_201_CREATED
    assert "state_hash" not in r.json()

    note_id = r.json()["id"]
    r = test_client.get(f"/api/notes/{note_id}", headers=headers)
    assert r.status_code == status.HTTP_200_OK
    assert "state_hash" not in r.json()
