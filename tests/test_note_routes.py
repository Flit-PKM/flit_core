"""Tests for notes list endpoint: filter by category name and search in title/content."""

import pytest
from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from auth.password import get_password_hash
from schemas.category import CategoryCreate
from schemas.note import NoteCreate
from schemas.note_category import NoteCategoryCreate
from service.category import create_category
from service.note import create_note
from service.note_category import link_note_category
from service.user import create_user


def _login(test_client, email: str, password: str) -> str:
    r = test_client.post(
        "/api/auth/login-json",
        json={"email": email, "password": password},
    )
    assert r.status_code == status.HTTP_200_OK
    return r.json()["access_token"]


@pytest.mark.asyncio
async def test_list_notes_filter_by_category_name(
    test_client,
    test_db_session: AsyncSession,
    sample_user_data: dict,
):
    """GET /notes?filter=<category_name> returns only notes linked to that category."""
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user = await create_user(test_db_session, user_data)

    work = await create_category(
        test_db_session, CategoryCreate(name="Work"), user.id
    )
    personal = await create_category(
        test_db_session, CategoryCreate(name="Personal"), user.id
    )

    note_work = await create_note(
        test_db_session,
        NoteCreate(
            user_id=user.id,
            title="Meeting notes",
            content="Discuss project",
            type="BASE",
        ),
    )
    note_personal = await create_note(
        test_db_session,
        NoteCreate(
            user_id=user.id,
            title="Grocery list",
            content="Milk and eggs",
            type="BASE",
        ),
    )
    note_work2 = await create_note(
        test_db_session,
        NoteCreate(
            user_id=user.id,
            title="Work task",
            content="Finish report",
            type="BASE",
        ),
    )
    await link_note_category(
        test_db_session, NoteCategoryCreate(note_id=note_work.id, category_id=work.id)
    )
    await link_note_category(
        test_db_session,
        NoteCategoryCreate(note_id=note_personal.id, category_id=personal.id),
    )
    await link_note_category(
        test_db_session, NoteCategoryCreate(note_id=note_work2.id, category_id=work.id)
    )
    await test_db_session.commit()

    token = _login(test_client, sample_user_data["email"], sample_user_data["password"])
    headers = {"Authorization": f"Bearer {token}"}

    r = test_client.get("/api/notes", params={"filter": "Work"}, headers=headers)
    assert r.status_code == status.HTTP_200_OK
    data = r.json()
    assert len(data) == 2
    ids = {n["id"] for n in data}
    assert ids == {note_work.id, note_work2.id}

    r = test_client.get("/api/notes", params={"filter": "Personal"}, headers=headers)
    assert r.status_code == status.HTTP_200_OK
    data = r.json()
    assert len(data) == 1
    assert data[0]["id"] == note_personal.id

    r = test_client.get("/api/notes", params={"filter": "NonExistent"}, headers=headers)
    assert r.status_code == status.HTTP_200_OK
    assert r.json() == []


@pytest.mark.asyncio
async def test_list_notes_search_content(
    test_client,
    test_db_session: AsyncSession,
    sample_user_data: dict,
):
    """GET /notes?search=<term> returns notes whose title or content contains term (case-insensitive)."""
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user = await create_user(test_db_session, user_data)

    note1 = await create_note(
        test_db_session,
        NoteCreate(
            user_id=user.id,
            title="Python tutorial",
            content="Learn basics",
            type="BASE",
        ),
    )
    note2 = await create_note(
        test_db_session,
        NoteCreate(
            user_id=user.id,
            title="Meeting",
            content="Discuss Python project",
            type="BASE",
        ),
    )
    note3 = await create_note(
        test_db_session,
        NoteCreate(
            user_id=user.id,
            title="Shopping",
            content="Buy milk",
            type="BASE",
        ),
    )
    await test_db_session.commit()

    token = _login(test_client, sample_user_data["email"], sample_user_data["password"])
    headers = {"Authorization": f"Bearer {token}"}

    r = test_client.get("/api/notes", params={"search": "python"}, headers=headers)
    assert r.status_code == status.HTTP_200_OK
    data = r.json()
    assert len(data) == 2
    ids = {n["id"] for n in data}
    assert ids == {note1.id, note2.id}

    r = test_client.get("/api/notes", params={"search": "Discuss"}, headers=headers)
    assert r.status_code == status.HTTP_200_OK
    data = r.json()
    assert len(data) == 1
    assert data[0]["id"] == note2.id

    r = test_client.get("/api/notes", params={"search": "xyz"}, headers=headers)
    assert r.status_code == status.HTTP_200_OK
    assert r.json() == []


@pytest.mark.asyncio
async def test_list_notes_filter_and_search_combined(
    test_client,
    test_db_session: AsyncSession,
    sample_user_data: dict,
):
    """GET /notes with both filter and search returns notes matching both."""
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user = await create_user(test_db_session, user_data)

    work = await create_category(
        test_db_session, CategoryCreate(name="Work"), user.id
    )

    note1 = await create_note(
        test_db_session,
        NoteCreate(
            user_id=user.id,
            title="Work item A",
            content="Task one",
            type="BASE",
        ),
    )
    note2 = await create_note(
        test_db_session,
        NoteCreate(
            user_id=user.id,
            title="Work item B",
            content="Task two",
            type="BASE",
        ),
    )
    note3 = await create_note(
        test_db_session,
        NoteCreate(
            user_id=user.id,
            title="Personal note",
            content="Work from home",
            type="BASE",
        ),
    )
    await link_note_category(
        test_db_session, NoteCategoryCreate(note_id=note1.id, category_id=work.id)
    )
    await link_note_category(
        test_db_session, NoteCategoryCreate(note_id=note2.id, category_id=work.id)
    )
    await link_note_category(
        test_db_session, NoteCategoryCreate(note_id=note3.id, category_id=work.id)
    )
    await test_db_session.commit()

    token = _login(test_client, sample_user_data["email"], sample_user_data["password"])
    headers = {"Authorization": f"Bearer {token}"}

    r = test_client.get(
        "/api/notes",
        params={"filter": "Work", "search": "Task"},
        headers=headers,
    )
    assert r.status_code == status.HTTP_200_OK
    data = r.json()
    assert len(data) == 2
    ids = {n["id"] for n in data}
    assert ids == {note1.id, note2.id}

    r = test_client.get(
        "/api/notes",
        params={"filter": "Work", "search": "one"},
        headers=headers,
    )
    assert r.status_code == status.HTTP_200_OK
    data = r.json()
    assert len(data) == 1
    assert data[0]["id"] == note1.id


@pytest.mark.asyncio
async def test_list_notes_without_filter_or_search_unchanged(
    test_client,
    test_db_session: AsyncSession,
    sample_user_data: dict,
):
    """GET /notes without filter/search returns all user notes (paginated)."""
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user = await create_user(test_db_session, user_data)

    await create_note(
        test_db_session,
        NoteCreate(
            user_id=user.id,
            title="Note one",
            content="Content one",
            type="BASE",
        ),
    )
    await create_note(
        test_db_session,
        NoteCreate(
            user_id=user.id,
            title="Note two",
            content="Content two",
            type="BASE",
        ),
    )
    await test_db_session.commit()

    token = _login(test_client, sample_user_data["email"], sample_user_data["password"])
    headers = {"Authorization": f"Bearer {token}"}

    r = test_client.get("/api/notes", headers=headers)
    assert r.status_code == status.HTTP_200_OK
    data = r.json()
    assert len(data) == 2
