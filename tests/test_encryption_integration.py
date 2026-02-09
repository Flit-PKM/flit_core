"""Integration tests: create note/chunk with encryption on, get and assert plaintext."""

import base64
import os
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from auth.password import get_password_hash
from models.chunk import Chunk
from models.note import Note
from schemas.chunk import ChunkCreate
from schemas.note import NoteCreate
from service.chunk import create_chunk, get_chunk
from service.note import create_note, get_note
from service.user import create_user


@pytest.mark.asyncio
async def test_note_encryption_roundtrip(
    test_db_session: AsyncSession,
    sample_user_data: dict,
    sample_note_data: dict,
    monkeypatch,
):
    """With encryption on for user: create note, get note, content and title match plaintext."""
    import config as config_module
    import service.encryption as enc_module
    import service.note as note_module
    key_b64 = base64.b64encode(os.urandom(32)).decode("utf-8")
    monkeypatch.setattr(config_module.settings, "ENCRYPTION_MASTER_KEY", key_b64)

    async def _encryption_enabled_for_user(_session, _user_id):
        return True

    async def _user_has_plan(_session, _user_id):
        return True

    monkeypatch.setattr(note_module, "is_encryption_enabled_for_user", _encryption_enabled_for_user)
    monkeypatch.setattr(enc_module, "user_has_encryption_plan", _user_has_plan)

    data = sample_user_data.copy()
    data["password_hash"] = get_password_hash(data.pop("password"))
    user = await create_user(test_db_session, data)
    await test_db_session.commit()

    note_create = NoteCreate(
        user_id=user.id,
        title=sample_note_data["title"],
        content=sample_note_data["content"],
        type=sample_note_data["type"],
    )
    created = await create_note(test_db_session, note_create)
    await test_db_session.commit()
    assert created.title == sample_note_data["title"]
    assert created.content == sample_note_data["content"]

    # Fetch from DB again (will be decrypted on read)
    fetched = await get_note(test_db_session, created.id)
    assert fetched is not None
    assert fetched.title == sample_note_data["title"]
    assert fetched.content == sample_note_data["content"]

    # encryption_version set indicates data is stored encrypted
    assert created.encryption_version == 1


@pytest.mark.asyncio
async def test_chunk_summary_encryption_roundtrip(
    test_db_session: AsyncSession,
    sample_user_data: dict,
    sample_note_data: dict,
    monkeypatch,
):
    """With encryption on for user: create note and chunk, get chunk, summary matches plaintext."""
    import config as config_module
    import service.encryption as enc_module
    import service.note as note_module
    import service.chunk as chunk_module
    key_b64 = base64.b64encode(os.urandom(32)).decode("utf-8")
    monkeypatch.setattr(config_module.settings, "ENCRYPTION_MASTER_KEY", key_b64)

    async def _encryption_enabled_for_user(_session, _user_id):
        return True

    async def _user_has_plan(_session, _user_id):
        return True

    monkeypatch.setattr(note_module, "is_encryption_enabled_for_user", _encryption_enabled_for_user)
    monkeypatch.setattr(chunk_module, "is_encryption_enabled_for_user", _encryption_enabled_for_user)
    monkeypatch.setattr(enc_module, "user_has_encryption_plan", _user_has_plan)

    data = sample_user_data.copy()
    data["password_hash"] = get_password_hash(data.pop("password"))
    user = await create_user(test_db_session, data)
    note_create = NoteCreate(
        user_id=user.id,
        title="Chunk test",
        content="Content",
        type="BASE",
    )
    note = await create_note(test_db_session, note_create)
    await test_db_session.commit()

    chunk_create = ChunkCreate(
        note_id=note.id,
        position_start=0,
        position_end=10,
        summary="Important summary text",
    )
    created = await create_chunk(test_db_session, chunk_create)
    await test_db_session.commit()
    assert created.summary == "Important summary text"

    fetched = await get_chunk(test_db_session, created.id)
    assert fetched is not None
    assert fetched.summary == "Important summary text"

    assert created.encryption_version == 1
