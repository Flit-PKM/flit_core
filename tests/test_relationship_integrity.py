"""Tests for relationship integrity: stale peers, cascade delete, hardened create/delete."""

from __future__ import annotations

import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.password import get_password_hash
from models.relationship import Relationship, RelationshipType
from schemas.note import NoteCreate
from schemas.relationship import RelationshipCreate
from schemas.sync import NoteSync, RelationshipSync
from service.note import create_note, delete_note
from service.relationship import (
    create_relationship,
    list_relationships_for_note,
    repair_stale_relationships,
)
from service.sync import sync_notes, sync_relationships
from service.user import create_user
from models.connected_app import ConnectedApp


def _login(test_client, email: str, password: str) -> str:
    r = test_client.post(
        "/api/auth/login-json",
        json={"email": email, "password": password},
    )
    assert r.status_code == status.HTTP_200_OK
    return r.json()["access_token"]


@pytest.mark.asyncio
async def test_create_relationship_rejects_self_loop(
    test_client,
    test_db_session: AsyncSession,
    sample_user_data: dict,
):
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user = await create_user(test_db_session, user_data)
    note = await create_note(
        test_db_session,
        NoteCreate(user_id=user.id, title="Solo", content="Body", type="BASE"),
    )
    await test_db_session.commit()

    token = _login(test_client, sample_user_data["email"], sample_user_data["password"])
    r = test_client.post(
        "/api/relationships",
        json={
            "note_a_id": note.id,
            "note_b_id": note.id,
            "type": "RELATED_TO",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


@pytest.mark.asyncio
async def test_create_relationship_rejects_deleted_peer(
    test_client,
    test_db_session: AsyncSession,
    sample_user_data: dict,
):
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user = await create_user(test_db_session, user_data)
    a = await create_note(
        test_db_session,
        NoteCreate(user_id=user.id, title="A", content="a", type="BASE"),
    )
    b = await create_note(
        test_db_session,
        NoteCreate(user_id=user.id, title="B", content="b", type="BASE"),
    )
    await delete_note(test_db_session, b.id, user.id)
    await test_db_session.commit()

    token = _login(test_client, sample_user_data["email"], sample_user_data["password"])
    r = test_client.post(
        "/api/relationships",
        json={
            "note_a_id": a.id,
            "note_b_id": b.id,
            "type": "RELATED_TO",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_delete_note_soft_deletes_relationships(
    test_db_session: AsyncSession,
    sample_user_data: dict,
):
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user = await create_user(test_db_session, user_data)
    a = await create_note(
        test_db_session,
        NoteCreate(user_id=user.id, title="A", content="a", type="BASE"),
    )
    b = await create_note(
        test_db_session,
        NoteCreate(user_id=user.id, title="B", content="b", type="BASE"),
    )
    await create_relationship(
        test_db_session,
        RelationshipCreate(
            note_a_id=a.id,
            note_b_id=b.id,
            type=RelationshipType.RELATED_TO,
        ),
        user.id,
    )
    await delete_note(test_db_session, b.id, user.id)
    await test_db_session.commit()

    rels = await list_relationships_for_note(test_db_session, a.id)
    assert rels == []


@pytest.mark.asyncio
async def test_sync_soft_delete_note_cascades_relationships(
    test_db_session: AsyncSession,
    sample_user_data: dict,
):
    """Sync note soft-delete must cascade like API delete_note."""
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user = await create_user(test_db_session, user_data)
    app = ConnectedApp(
        user_id=user.id,
        app_slug="flit",
        device_name="Test",
        platform="test",
        app_version="1.0",
    )
    test_db_session.add(app)
    await test_db_session.flush()
    a = await create_note(
        test_db_session,
        NoteCreate(user_id=user.id, title="A", content="a", type="BASE"),
    )
    b = await create_note(
        test_db_session,
        NoteCreate(user_id=user.id, title="B", content="b", type="BASE"),
    )
    await create_relationship(
        test_db_session,
        RelationshipCreate(
            note_a_id=a.id,
            note_b_id=b.id,
            type=RelationshipType.RELATED_TO,
        ),
        user.id,
    )
    await test_db_session.commit()

    results = await sync_notes(
        test_db_session,
        user_id=user.id,
        connected_app_id=app.id,
        notes=[
            NoteSync(
                core_id=b.id,
                title="B",
                content="b",
                type="BASE",
                version=b.version + 1,
                is_deleted=True,
            )
        ],
    )
    assert results[0].status == "updated"
    rels = await list_relationships_for_note(test_db_session, a.id)
    assert rels == []


@pytest.mark.asyncio
async def test_get_note_hides_relationship_to_deleted_peer(
    test_client,
    test_db_session: AsyncSession,
    sample_user_data: dict,
):
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user = await create_user(test_db_session, user_data)
    a = await create_note(
        test_db_session,
        NoteCreate(user_id=user.id, title="A", content="a", type="BASE"),
    )
    b = await create_note(
        test_db_session,
        NoteCreate(user_id=user.id, title="B", content="b", type="BASE"),
    )
    await create_relationship(
        test_db_session,
        RelationshipCreate(
            note_a_id=a.id,
            note_b_id=b.id,
            type=RelationshipType.RELATED_TO,
        ),
        user.id,
    )
    await test_db_session.commit()

    token = _login(test_client, sample_user_data["email"], sample_user_data["password"])
    headers = {"Authorization": f"Bearer {token}"}

    r = test_client.get(f"/api/notes/{a.id}", headers=headers)
    assert r.status_code == status.HTTP_200_OK
    assert len(r.json()["relationships"]) == 1

    await delete_note(test_db_session, b.id, user.id)
    await test_db_session.commit()

    r = test_client.get(f"/api/notes/{a.id}", headers=headers)
    assert r.status_code == status.HTTP_200_OK
    assert r.json()["relationships"] == []


@pytest.mark.asyncio
async def test_delete_relationship_when_peer_note_deleted(
    test_client,
    test_db_session: AsyncSession,
    sample_user_data: dict,
):
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user = await create_user(test_db_session, user_data)
    a = await create_note(
        test_db_session,
        NoteCreate(user_id=user.id, title="A", content="a", type="BASE"),
    )
    b = await create_note(
        test_db_session,
        NoteCreate(user_id=user.id, title="B", content="b", type="BASE"),
    )
    await create_relationship(
        test_db_session,
        RelationshipCreate(
            note_a_id=a.id,
            note_b_id=b.id,
            type=RelationshipType.RELATED_TO,
        ),
        user.id,
    )
    await delete_note(test_db_session, b.id, user.id)
    await test_db_session.commit()

    token = _login(test_client, sample_user_data["email"], sample_user_data["password"])
    r = test_client.delete(
        f"/api/relationships/{a.id}/{b.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == status.HTTP_204_NO_CONTENT


@pytest.mark.asyncio
async def test_delete_relationship_stale_row_peer_deleted(
    test_client,
    test_db_session: AsyncSession,
    sample_user_data: dict,
):
    """Stale relationship row (peer deleted before cascade) can still be removed."""
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user = await create_user(test_db_session, user_data)
    a = await create_note(
        test_db_session,
        NoteCreate(user_id=user.id, title="A", content="a", type="BASE"),
    )
    b = await create_note(
        test_db_session,
        NoteCreate(user_id=user.id, title="B", content="b", type="BASE"),
    )
    await create_relationship(
        test_db_session,
        RelationshipCreate(
            note_a_id=a.id,
            note_b_id=b.id,
            type=RelationshipType.RELATED_TO,
        ),
        user.id,
    )
    await delete_note(test_db_session, b.id, user.id)
    # Simulate legacy stale row: re-activate relationship without restoring note b
    result = await test_db_session.execute(
        select(Relationship).where(
            Relationship.note_a_id == a.id,
            Relationship.note_b_id == b.id,
        )
    )
    rel = result.scalar_one()
    rel.is_deleted = False
    await test_db_session.commit()

    token = _login(test_client, sample_user_data["email"], sample_user_data["password"])
    r = test_client.get(f"/api/notes/{a.id}", headers={"Authorization": f"Bearer {token}"})
    assert r.json()["relationships"] == []

    r = test_client.delete(
        f"/api/relationships/{a.id}/{b.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == status.HTTP_204_NO_CONTENT


@pytest.mark.asyncio
async def test_sync_push_relationship_rejects_deleted_note(
    test_db_session: AsyncSession,
    sample_user_data: dict,
):
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user = await create_user(test_db_session, user_data)
    a = await create_note(
        test_db_session,
        NoteCreate(user_id=user.id, title="A", content="a", type="BASE"),
    )
    b = await create_note(
        test_db_session,
        NoteCreate(user_id=user.id, title="B", content="b", type="BASE"),
    )
    await delete_note(test_db_session, b.id, user.id)
    await test_db_session.commit()

    results = await sync_relationships(
        test_db_session,
        user.id,
        [
            RelationshipSync(
                note_a_core_id=a.id,
                note_b_core_id=b.id,
                type=RelationshipType.RELATED_TO,
                version=1,
                is_deleted=False,
            )
        ],
        commit=False,
    )
    assert results[0].status == "rejected"


@pytest.mark.asyncio
async def test_repair_stale_relationships(
    test_db_session: AsyncSession,
    sample_user_data: dict,
):
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user = await create_user(test_db_session, user_data)
    a = await create_note(
        test_db_session,
        NoteCreate(user_id=user.id, title="A", content="a", type="BASE"),
    )
    b = await create_note(
        test_db_session,
        NoteCreate(user_id=user.id, title="B", content="b", type="BASE"),
    )
    await create_relationship(
        test_db_session,
        RelationshipCreate(
            note_a_id=a.id,
            note_b_id=b.id,
            type=RelationshipType.RELATED_TO,
        ),
        user.id,
    )
    await delete_note(test_db_session, b.id, user.id)
    # Legacy: relationship still active
    result = await test_db_session.execute(
        select(Relationship).where(
            Relationship.note_a_id == a.id,
            Relationship.note_b_id == b.id,
        )
    )
    rel = result.scalar_one()
    rel.is_deleted = False
    await test_db_session.flush()

    count = await repair_stale_relationships(test_db_session)
    assert count == 1
    rels = await list_relationships_for_note(test_db_session, a.id)
    assert rels == []
