"""Tests for notes list endpoint: filter by category name and search in title/content."""

import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.password import get_password_hash
from models.notesearch import NoteSearch
from schemas.category import CategoryCreate
from schemas.note import NoteCreate, NoteUpdate
from schemas.note_category import NoteCategoryCreate
from service.category import create_category
from service.note import create_note, delete_note, update_note
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


# ----- Notesearch persistence (non-encrypted only) -----


@pytest.mark.asyncio
async def test_notesearch_row_created_on_create_note(
    test_db_session: AsyncSession,
    sample_user_data: dict,
):
    """Creating a note (encryption off) inserts a notesearch row with normalized content."""
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user = await create_user(test_db_session, user_data)
    await test_db_session.commit()

    note = await create_note(
        test_db_session,
        NoteCreate(
            user_id=user.id,
            title="Python Tutorial",
            content="Learn the basics",
            type="BASE",
        ),
    )
    await test_db_session.commit()

    result = await test_db_session.execute(
        select(NoteSearch).where(NoteSearch.note_id == note.id)
    )
    row = result.scalar_one_or_none()
    assert row is not None
    assert row.user_id == user.id
    assert "python" in row.content
    assert "tutorial" in row.content
    assert "learn" in row.content
    assert "basics" in row.content
    assert "the" not in row.content  # stopword removed


@pytest.mark.asyncio
async def test_notesearch_row_updated_on_update_note(
    test_db_session: AsyncSession,
    sample_user_data: dict,
):
    """Updating a note (encryption off) updates the notesearch row."""
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user = await create_user(test_db_session, user_data)
    await test_db_session.commit()

    note = await create_note(
        test_db_session,
        NoteCreate(
            user_id=user.id,
            title="Old title",
            content="Old content",
            type="BASE",
        ),
    )
    await test_db_session.commit()

    await update_note(
        test_db_session,
        note.id,
        NoteUpdate(title="New title", content="New content"),
    )
    await test_db_session.commit()

    result = await test_db_session.execute(
        select(NoteSearch).where(NoteSearch.note_id == note.id)
    )
    row = result.scalar_one_or_none()
    assert row is not None
    assert "new" in row.content
    assert "title" in row.content
    assert "old" not in row.content


@pytest.mark.asyncio
async def test_notesearch_row_deleted_on_soft_delete_note(
    test_db_session: AsyncSession,
    sample_user_data: dict,
):
    """Soft-deleting a note hard-deletes the notesearch row."""
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user = await create_user(test_db_session, user_data)
    await test_db_session.commit()

    note = await create_note(
        test_db_session,
        NoteCreate(
            user_id=user.id,
            title="To delete",
            content="Content",
            type="BASE",
        ),
    )
    await test_db_session.commit()

    result = await test_db_session.execute(
        select(NoteSearch).where(NoteSearch.note_id == note.id)
    )
    assert result.scalar_one_or_none() is not None

    await delete_note(test_db_session, note.id, user.id)
    await test_db_session.commit()

    result = await test_db_session.execute(
        select(NoteSearch).where(NoteSearch.note_id == note.id)
    )
    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_no_notesearch_row_when_encryption_enabled(
    test_db_session: AsyncSession,
    sample_user_data: dict,
    monkeypatch,
):
    """When encryption is enabled for the user, no notesearch row is created."""
    import base64
    import os

    import config as config_module
    import service.encryption as enc_module

    key_b64 = base64.b64encode(os.urandom(32)).decode("utf-8")
    monkeypatch.setattr(config_module.settings, "ENCRYPTION_MASTER_KEY", key_b64)

    async def _encryption_enabled(_session, _user_id):
        return True

    async def _user_has_plan(_session, _user_id):
        return True

    monkeypatch.setattr(
        enc_module, "is_encryption_enabled_for_user", _encryption_enabled
    )
    monkeypatch.setattr(enc_module, "user_has_encryption_plan", _user_has_plan)

    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user = await create_user(test_db_session, user_data)
    await test_db_session.commit()

    note = await create_note(
        test_db_session,
        NoteCreate(
            user_id=user.id,
            title="Secret",
            content="Encrypted content",
            type="BASE",
        ),
    )
    await test_db_session.commit()

    result = await test_db_session.execute(
        select(NoteSearch).where(NoteSearch.note_id == note.id)
    )
    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_search_prefix_match(
    test_client,
    test_db_session: AsyncSession,
    sample_user_data: dict,
):
    """Search with prefix of a word (e.g. 'pyth') matches notes containing 'python'."""
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user = await create_user(test_db_session, user_data)

    await create_note(
        test_db_session,
        NoteCreate(
            user_id=user.id,
            title="Python basics",
            content="Get started",
            type="BASE",
        ),
    )
    await test_db_session.commit()

    token = _login(test_client, sample_user_data["email"], sample_user_data["password"])
    headers = {"Authorization": f"Bearer {token}"}

    r = test_client.get("/api/notes", params={"search": "pyth"}, headers=headers)
    assert r.status_code == status.HTTP_200_OK
    data = r.json()
    assert len(data) == 1
    assert "python" in data[0]["title"].lower() or "python" in data[0]["content"].lower()


@pytest.mark.asyncio
async def test_search_multi_word_returns_notes_matching_both(
    test_client,
    test_db_session: AsyncSession,
    sample_user_data: dict,
):
    """Search with multiple words returns notes that match (prefix/substring) for the query."""
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user = await create_user(test_db_session, user_data)

    note1 = await create_note(
        test_db_session,
        NoteCreate(
            user_id=user.id,
            title="Python tutorial",
            content="Learn programming",
            type="BASE",
        ),
    )
    await create_note(
        test_db_session,
        NoteCreate(
            user_id=user.id,
            title="Meeting",
            content="Discuss project",
            type="BASE",
        ),
    )
    await create_note(
        test_db_session,
        NoteCreate(
            user_id=user.id,
            title="Tutorial",
            content="Python guide",
            type="BASE",
        ),
    )
    await test_db_session.commit()

    token = _login(test_client, sample_user_data["email"], sample_user_data["password"])
    headers = {"Authorization": f"Bearer {token}"}

    r = test_client.get(
        "/api/notes",
        params={"search": "python tutorial"},
        headers=headers,
    )
    assert r.status_code == status.HTTP_200_OK
    data = r.json()
    assert len(data) >= 2  # note1 and tutorial+python note both match
    ids = {n["id"] for n in data}
    assert note1.id in ids
