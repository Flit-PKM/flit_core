"""Tests for vault markdown import/export endpoints."""

from __future__ import annotations

import io
import zipfile

import pytest
import yaml
from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.password import get_password_hash
from models.note import Note
from models.relationship import Relationship, RelationshipType
from schemas.category import CategoryCreate
from schemas.note import NoteCreate
from schemas.note_category import NoteCategoryCreate
from schemas.relationship import RelationshipCreate
from service.category import create_category
from service.note import create_note
from service.note_category import link_note_category
from service.relationship import create_relationship
from service.user import create_user
from service.vault_markdown import (
    make_link_key,
    parse_markdown_note_file,
    render_note_markdown,
)


def _login(test_client, email: str, password: str) -> str:
    r = test_client.post(
        "/api/auth/login-json",
        json={"email": email, "password": password},
    )
    assert r.status_code == status.HTTP_200_OK
    return r.json()["access_token"]


async def _setup_user(test_db_session: AsyncSession, sample_user_data: dict):
    user_data = sample_user_data.copy()
    user_data["password_hash"] = get_password_hash(user_data.pop("password"))
    user = await create_user(test_db_session, user_data)
    await test_db_session.commit()
    return user


def test_make_link_key_sanitizes_title():
    assert make_link_key("Hello / World", 42) == "Hello _ World_42"


def test_parse_markdown_note_file_with_frontmatter():
    text = """---
title: My Idea
categories:
  - Work
created: 2024-01-15T12:00:00Z
updated: 2024-01-16T12:00:00Z
status: PUBLISHED
---
First paragraph.

## Relationships
**Similar To**: [[Other note_12]]
**Follows to**: [[Parent topic_3]]
"""
    from datetime import datetime, timezone

    import_time = datetime(2025, 1, 1, tzinfo=timezone.utc)
    parsed = parse_markdown_note_file(text, "My Idea_7", import_time=import_time)
    assert parsed.title == "My Idea"
    assert parsed.categories == ["Work"]
    assert "First paragraph." in parsed.body
    assert "## Relationships" not in parsed.body
    assert len(parsed.relationships) == 2
    assert parsed.relationships[0].label == "Similar To"
    assert parsed.relationships[0].target_link_key == "Other note_12"


@pytest.mark.asyncio
async def test_export_fails_with_no_notes(
    test_client,
    test_db_session: AsyncSession,
    sample_user_data: dict,
):
    await _setup_user(test_db_session, sample_user_data)
    token = _login(test_client, sample_user_data["email"], sample_user_data["password"])
    r = test_client.get(
        "/api/vault/markdown-export",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == status.HTTP_400_BAD_REQUEST
    assert r.json()["detail"] == "no notes to export"


@pytest.mark.asyncio
async def test_export_zip_structure(
    test_client,
    test_db_session: AsyncSession,
    sample_user_data: dict,
):
    user = await _setup_user(test_db_session, sample_user_data)
    note = await create_note(
        test_db_session,
        NoteCreate(
            user_id=user.id,
            title="My Idea",
            content="Body text",
            type="BASE",
        ),
    )
    work = await create_category(
        test_db_session, CategoryCreate(name="Work"), user.id
    )
    await link_note_category(
        test_db_session,
        NoteCategoryCreate(note_id=note.id, category_id=work.id),
    )
    await test_db_session.commit()

    token = _login(test_client, sample_user_data["email"], sample_user_data["password"])
    r = test_client.get(
        "/api/vault/markdown-export",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == status.HTTP_200_OK
    assert r.headers["content-type"] == "application/zip"
    assert "flit-" in r.headers.get("content-disposition", "")
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = sorted(zf.namelist())
    assert len(names) == 1
    assert names[0] == f"{make_link_key('My Idea', note.id)}.md"
    content = zf.read(names[0]).decode("utf-8")
    assert content.startswith("---\n")
    assert "Body text" in content
    assert "Work" in content


@pytest.mark.asyncio
async def test_import_single_md_file(
    test_client,
    test_db_session: AsyncSession,
    sample_user_data: dict,
):
    await _setup_user(test_db_session, sample_user_data)
    token = _login(test_client, sample_user_data["email"], sample_user_data["password"])
    md = """---
title: Imported Note
categories:
  - Personal
---
Hello from import.
"""
    r = test_client.post(
        "/api/vault/markdown-import",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("note.md", md.encode("utf-8"), "text/markdown")},
    )
    assert r.status_code == status.HTTP_200_OK
    data = r.json()
    assert data["notes_imported"] == 1
    assert data["relationships_imported"] == 0

    result = await test_db_session.execute(
        select(Note).where(Note.title == "Imported Note", Note.is_deleted == False)
    )
    note = result.scalar_one_or_none()
    assert note is not None
    assert "Hello from import." in note.content


@pytest.mark.asyncio
async def test_import_zip_with_relationships(
    test_client,
    test_db_session: AsyncSession,
    sample_user_data: dict,
):
    await _setup_user(test_db_session, sample_user_data)
    token = _login(test_client, sample_user_data["email"], sample_user_data["password"])

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "Parent topic_3.md",
            """---
title: Parent topic
---
Parent body.
""",
        )
        zf.writestr(
            "My Idea_7.md",
            """---
title: My Idea
---
First paragraph.

## Relationships
**Similar To**: [[Other note_12]]
**Follows to**: [[Parent topic_3]]
""",
        )
        zf.writestr(
            "Other note_12.md",
            """---
title: Other note
---
Other body.
""",
        )
    buf.seek(0)

    r = test_client.post(
        "/api/vault/markdown-import",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("backup.zip", buf.read(), "application/zip")},
    )
    assert r.status_code == status.HTTP_200_OK
    data = r.json()
    assert data["notes_imported"] == 3
    assert data["relationships_imported"] == 2
    assert data["relationships_skipped"] == 0


@pytest.mark.asyncio
async def test_import_zip_rejects_nested_paths(
    test_client,
    test_db_session: AsyncSession,
    sample_user_data: dict,
):
    await _setup_user(test_db_session, sample_user_data)
    token = _login(test_client, sample_user_data["email"], sample_user_data["password"])

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("notes/My Idea_7.md", "---\ntitle: x\n---\nbody")
    buf.seek(0)

    r = test_client.post(
        "/api/vault/markdown-import",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("bad.zip", buf.read(), "application/zip")},
    )
    assert r.status_code == status.HTTP_400_BAD_REQUEST
    assert "root .md" in r.json()["detail"]


@pytest.mark.asyncio
async def test_import_merge_only_duplicates_notes(
    test_client,
    test_db_session: AsyncSession,
    sample_user_data: dict,
):
    await _setup_user(test_db_session, sample_user_data)
    token = _login(test_client, sample_user_data["email"], sample_user_data["password"])
    md = "---\ntitle: Dup\n---\nbody\n"
    for _ in range(2):
        r = test_client.post(
            "/api/vault/markdown-import",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("dup.md", md.encode("utf-8"), "text/markdown")},
        )
        assert r.status_code == status.HTTP_200_OK

    result = await test_db_session.execute(
        select(Note).where(Note.title == "Dup", Note.is_deleted == False)
    )
    assert len(result.scalars().all()) == 2


@pytest.mark.asyncio
async def test_import_relationship_deduplication_and_skips(
    test_client,
    test_db_session: AsyncSession,
    sample_user_data: dict,
):
    user = await _setup_user(test_db_session, sample_user_data)
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
            type=RelationshipType.SIMILAR_TO,
        ),
    )
    await test_db_session.commit()

    token = _login(test_client, sample_user_data["email"], sample_user_data["password"])
    key_a = make_link_key("A", a.id)
    key_b = make_link_key("B", b.id)
    md_a = f"""---
title: A
---
body

## Relationships
**Similar To**: [[{key_b}]]
**Unknown Label**: [[{key_b}]]
**Similar To**: [[{key_b}]]
"""
    md_b = f"""---
title: B
---
body
"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"{key_a}.md", md_a)
        zf.writestr(f"{key_b}.md", md_b)
    buf.seek(0)

    r = test_client.post(
        "/api/vault/markdown-import",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("batch.zip", buf.read(), "application/zip")},
    )
    assert r.status_code == status.HTTP_200_OK
    data = r.json()
    assert data["notes_imported"] == 2
    assert data["relationships_imported"] == 1
    assert data["relationships_skipped"] == 2


@pytest.mark.asyncio
async def test_export_import_round_trip_content(
    test_client,
    test_db_session: AsyncSession,
    sample_user_data: dict,
):
    user = await _setup_user(test_db_session, sample_user_data)
    n1 = await create_note(
        test_db_session,
        NoteCreate(
            user_id=user.id,
            title="Alpha",
            content="Alpha body",
            type="BASE",
        ),
    )
    n2 = await create_note(
        test_db_session,
        NoteCreate(
            user_id=user.id,
            title="Beta",
            content="Beta body",
            type="BASE",
        ),
    )
    await create_relationship(
        test_db_session,
        RelationshipCreate(
            note_a_id=n1.id,
            note_b_id=n2.id,
            type=RelationshipType.RELATED_TO,
        ),
    )
    await test_db_session.commit()

    token = _login(test_client, sample_user_data["email"], sample_user_data["password"])
    export_r = test_client.get(
        "/api/vault/markdown-export",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert export_r.status_code == status.HTTP_200_OK

    import_r = test_client.post(
        "/api/vault/markdown-import",
        headers={"Authorization": f"Bearer {token}"},
        files={
            "file": (
                "roundtrip.zip",
                export_r.content,
                "application/zip",
            )
        },
    )
    assert import_r.status_code == status.HTTP_200_OK
    data = import_r.json()
    assert data["notes_imported"] == 2
    assert data["relationships_imported"] == 1

    result = await test_db_session.execute(
        select(Note).where(
            Note.user_id == user.id,
            Note.is_deleted == False,
        )
    )
    notes = list(result.scalars().all())
    assert len(notes) == 4
    assert sorted(n.title for n in notes) == ["Alpha", "Alpha", "Beta", "Beta"]

    rel_result = await test_db_session.execute(
        select(Relationship).where(Relationship.is_deleted == False)
    )
    assert len(rel_result.scalars().all()) == 2


def test_render_note_markdown_includes_relationships():
    from datetime import datetime, timezone

    note = Note(
        id=7,
        title="My Idea",
        content="Body",
        user_id=1,
        created_at=datetime(2024, 1, 15, 12, 0, tzinfo=timezone.utc),
        updated_at=datetime(2024, 1, 16, 12, 0, tzinfo=timezone.utc),
    )
    md = render_note_markdown(
        note,
        ["Work"],
        [("Similar To", "Other note_12")],
    )
    assert "## Relationships" in md
    assert "**Similar To**: [[Other note_12]]" in md
    fm = md.split("---\n")[1]
    meta = yaml.safe_load(fm)
    assert meta["title"] == "My Idea"
    assert meta["categories"] == ["Work"]
