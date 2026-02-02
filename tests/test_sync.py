"""Tests for sync: compare (deleted notes), push is_deleted, get_notes includes is_deleted."""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.password import get_password_hash
from models.chunk import Chunk
from models.connected_app import ConnectedApp
from models.note import Note
from models.user import User
from schemas.sync import ChunkVersion, NoteSync, NoteVersion
from service.oauth import issue_tokens_for_connected_app
from service.sync import compare_chunks, compare_notes, get_notes_by_ids, sync_notes


@pytest_asyncio.fixture
async def sync_test_data(test_db_session: AsyncSession):
    """User, connected_app, and optional note for sync tests."""
    user = User(
        username="syncuser",
        email="sync@example.com",
        password_hash=get_password_hash("password123"),
        is_active=True,
        is_verified=False,
    )
    test_db_session.add(user)
    await test_db_session.flush()

    app = ConnectedApp(
        user_id=user.id,
        app_slug="flit",
        device_name="Test Device",
        platform="test",
        app_version="1.0",
    )
    test_db_session.add(app)
    await test_db_session.flush()

    await test_db_session.commit()
    return {"user": user, "connected_app": app}


@pytest.mark.asyncio
async def test_compare_omits_deleted_note_from_to_pull(
    test_db_session: AsyncSession,
    sync_test_data: dict,
):
    """Server has a soft-deleted note → it is NOT in to_pull (is_deleted omits from pull list)."""
    user = sync_test_data["user"]
    app = sync_test_data["connected_app"]

    note = Note(
        title="Deleted Note",
        content="Will be deleted",
        type="BASE",
        version=2,
        user_id=user.id,
        source_id=app.id,
        is_deleted=True,
    )
    test_db_session.add(note)
    await test_db_session.flush()
    await test_db_session.commit()

    # App sends empty list -> server's is_deleted note is omitted from to_pull
    response = await compare_notes(
        test_db_session,
        user_id=user.id,
        connected_app_id=app.id,
        app_notes=[],
    )
    assert len(response.to_pull) == 0


@pytest.mark.asyncio
async def test_compare_reports_to_push_when_core_id_missing(
    test_db_session: AsyncSession,
    sync_test_data: dict,
):
    """When app sends entity with no core_id and not is_deleted, compare reports it in to_push (read-only; no DB write)."""
    user = sync_test_data["user"]
    app = sync_test_data["connected_app"]

    # App has new local note: app_id only, no core_id
    response = await compare_notes(
        test_db_session,
        user_id=user.id,
        connected_app_id=app.id,
        app_notes=[
            NoteVersion(app_id="local-uuid-1", core_id=None, version=1, is_deleted=False),
        ],
    )
    assert len(response.to_push) == 1
    entry = response.to_push[0]
    assert entry.app_id == "local-uuid-1"
    assert entry.core_id is None
    assert entry.version == 1
    assert entry.is_deleted is False
    # Compare is read-only: no Note row was created
    from sqlalchemy import select

    r = await test_db_session.execute(select(Note).where(Note.user_id == user.id))
    notes = list(r.scalars().all())
    assert len(notes) == 0


@pytest.mark.asyncio
async def test_compare_deleted_note_in_to_pull(
    test_db_session: AsyncSession,
    sync_test_data: dict,
):
    """Server has deleted note with newer version → appears in to_pull."""
    user = sync_test_data["user"]
    app = sync_test_data["connected_app"]

    note = Note(
        title="Deleted Note",
        content="Will be deleted",
        type="BASE",
        version=3,
        user_id=user.id,
        source_id=app.id,
        is_deleted=True,
    )
    test_db_session.add(note)
    await test_db_session.flush()
    await test_db_session.commit()

    # App has old version -> deleted note still in to_pull (outdated server copy includes is_deleted)
    response = await compare_notes(
        test_db_session,
        user_id=user.id,
        connected_app_id=app.id,
        app_notes=[NoteVersion(core_id=note.id, version=1, is_deleted=False)],
    )
    assert len(response.to_pull) == 1
    assert response.to_pull[0].core_id == note.id
    assert response.to_pull[0].version == 3
    assert response.to_pull[0].is_deleted is True


@pytest.mark.asyncio
async def test_push_is_deleted_marks_note_deleted(
    test_db_session: AsyncSession,
    sync_test_data: dict,
):
    """Push with is_deleted=True marks the note soft-deleted and updates version."""
    user = sync_test_data["user"]
    app = sync_test_data["connected_app"]

    note = Note(
        title="To Delete",
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

    notes = [
        NoteSync(
            core_id=note_id,
            title="To Delete",
            content="Content",
            type="BASE",
            version=2,
            is_deleted=True,
        )
    ]
    results = await sync_notes(
        test_db_session,
        user_id=user.id,
        connected_app_id=app.id,
        notes=notes,
    )
    assert len(results) == 1
    assert results[0].status == "updated"
    assert results[0].server_version == 2

    # Reload note from same session (session was committed by sync_notes)
    from sqlalchemy import select

    r = await test_db_session.execute(select(Note).where(Note.id == note_id))
    updated = r.scalar_one_or_none()
    assert updated is not None
    assert updated.is_deleted is True
    assert updated.version == 2


@pytest.mark.asyncio
async def test_push_creates_note_when_core_id_none(
    test_db_session: AsyncSession,
    sync_test_data: dict,
):
    """Push with core_id=None creates a new note; compare is read-only and does not create placeholders."""
    user = sync_test_data["user"]
    app = sync_test_data["connected_app"]

    # Push with core_id=None creates the note
    results = await sync_notes(
        test_db_session,
        user_id=user.id,
        connected_app_id=app.id,
        notes=[
            NoteSync(
                core_id=None,
                title="Filled In",
                content="Body",
                type="BASE",
                version=1,
                is_deleted=False,
            )
        ],
    )
    assert len(results) == 1
    assert results[0].status == "created"
    assert results[0].server_version == 1
    core_id = results[0].core_id
    assert core_id is not None

    from sqlalchemy import select

    r = await test_db_session.execute(select(Note).where(Note.id == core_id))
    db_note = r.scalar_one_or_none()
    assert db_note is not None
    assert db_note.title == "Filled In"
    assert db_note.content == "Body"


@pytest.mark.asyncio
async def test_get_notes_by_ids_includes_deleted(
    test_db_session: AsyncSession,
    sync_test_data: dict,
):
    """get_notes_by_ids returns notes with is_deleted=True so clients can remove them."""
    user = sync_test_data["user"]
    app = sync_test_data["connected_app"]

    note = Note(
        title="Deleted",
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

    notes = await get_notes_by_ids(test_db_session, user_id=user.id, note_ids=[note_id])
    assert len(notes) == 1
    assert notes[0].id == note_id
    assert notes[0].is_deleted is True


@pytest.mark.asyncio
async def test_compare_chunks_does_not_create_db_rows_when_core_id_none(
    test_db_session: AsyncSession,
    sync_test_data: dict,
):
    """compare_chunks is read-only: when app sends chunk with core_id=None, no Chunk row is created."""
    user = sync_test_data["user"]
    app = sync_test_data["connected_app"]

    note = Note(
        title="Chunk Note",
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

    response = await compare_chunks(
        test_db_session,
        user_id=user.id,
        app_chunks=[
            ChunkVersion(
                app_id="local-chunk-1",
                core_id=None,
                note_core_id=note_id,
                version=1,
                is_deleted=False,
            ),
        ],
    )
    assert len(response.to_push) == 1
    assert response.to_push[0].core_id is None
    assert response.to_push[0].app_id == "local-chunk-1"

    r = await test_db_session.execute(select(Chunk))
    chunks = list(r.scalars().all())
    assert len(chunks) == 0


@pytest.mark.asyncio
async def test_sync_compare_notes_with_oauth_token(
    test_client,
    test_db_session: AsyncSession,
    sync_test_data: dict,
):
    """Sync compare endpoint accepts valid OAuth token and returns 200."""
    user = sync_test_data["user"]
    app = sync_test_data["connected_app"]
    access_token, _ = await issue_tokens_for_connected_app(
        test_db_session, app.id, user.id
    )
    await test_db_session.commit()

    r = test_client.post(
        "/sync/compare/notes",
        json={"notes": []},
        headers={"Authorization": f"Bearer {access_token.token}"},
    )
    assert r.status_code == 200
