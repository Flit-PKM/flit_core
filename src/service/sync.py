"""Sync service: compare (read-only) and push (create/update) for notes, categories, relationships, chunks, note_categories.

Compare functions are read-only; they never create, update, or delete rows in the DB.
Compare returns to_pull (app should GET) and to_push (app should POST); hard-removed entities (missing + is_deleted) are omitted from to_push.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from logging_config import get_logger
from models.category import Category
from models.chunk import Chunk
from models.note import Note, NoteType
from models.note_category import NoteCategory
from models.relationship import Relationship
from schemas.note import NoteCreate
from schemas.sync import (
    CategoryVersion,
    ChunkVersion,
    NoteCategoryVersion,
    NoteSync,
    NoteVersion,
    RelationshipVersion,
)

logger = get_logger(__name__)


def _notes_compare_result(
    missing_on_server: list,
    outdated_on_server: list,
    missing_on_app: list,
    outdated_on_app: list,
):
    from schemas.sync import NotesCompareResult

    return NotesCompareResult(
        to_pull=missing_on_app + outdated_on_app,
        to_push=missing_on_server + outdated_on_server,
    )


async def compare_notes(
    session: AsyncSession,
    user_id: int,
    connected_app_id: int,
    app_notes: list[NoteVersion],
):
    """Compare app's note list with server. Read-only: does not create placeholders; returns to_pull and to_push (to_push includes new app items with core_id=None)."""
    core_ids_from_request = {nv.core_id for nv in app_notes if nv.core_id is not None}
    app_versions_by_core_id = {nv.core_id: nv.version for nv in app_notes if nv.core_id is not None}

    if not app_notes:
        # App has no notes, return all server notes for this user (exclude is_deleted)
        result = await session.execute(
            select(Note).where(Note.user_id == user_id)
        )
        server_notes = list(result.scalars().all())
        return _notes_compare_result(
            missing_on_server=[],
            outdated_on_server=[],
            missing_on_app=[
                NoteVersion(core_id=note.id, version=note.version, is_deleted=note.is_deleted)
                for note in server_notes
                if not note.is_deleted
            ],
            outdated_on_app=[],
        )

    # Load server notes by core_id
    server_notes = {}
    if core_ids_from_request:
        result = await session.execute(
            select(Note).where(
                Note.id.in_(core_ids_from_request),
                Note.user_id == user_id,
            )
        )
        server_notes = {note.id: note for note in result.scalars().all()}

    missing_on_server = []
    outdated_on_server = []
    missing_on_app = []
    outdated_on_app = []

    for app_note in app_notes:
        core_id = app_note.core_id
        app_version = app_note.version

        if core_id is not None:
            # Has core_id: compare with server row
            if core_id not in server_notes:
                if not app_note.is_deleted:
                    missing_on_server.append(app_note)
            else:
                server_note = server_notes[core_id]
                if app_version > server_note.version:
                    outdated_on_server.append(app_note)
        else:
            # No core_id
            if not app_note.is_deleted:
                missing_on_server.append(
                    NoteVersion(
                        app_id=app_note.app_id,
                        core_id=None,
                        version=app_version or 1,
                        is_deleted=False,
                    )
                )
            # is_deleted and no core_id: local-only delete, skip

    # Server notes this app doesn't have (for this user)
    result = await session.execute(
        select(Note).where(Note.user_id == user_id)
    )
    all_server_notes = {note.id: note for note in result.scalars().all()}

    for note_id, server_note in all_server_notes.items():
        if note_id not in core_ids_from_request:
            if not server_note.is_deleted:
                missing_on_app.append(
                    NoteVersion(
                        core_id=note_id,
                        version=server_note.version,
                        is_deleted=server_note.is_deleted,
                    )
                )
        elif note_id in server_notes:
            app_ver = app_versions_by_core_id.get(note_id, 0)
            if server_note.version > app_ver:
                outdated_on_app.append(
                    NoteVersion(
                        core_id=note_id,
                        version=server_note.version,
                        is_deleted=server_note.is_deleted,
                    )
                )

    return _notes_compare_result(
        missing_on_server=missing_on_server,
        outdated_on_server=outdated_on_server,
        missing_on_app=missing_on_app,
        outdated_on_app=outdated_on_app,
    )


async def sync_notes(
    session: AsyncSession,
    user_id: int,
    connected_app_id: int,
    notes: list["NoteSync"],
    *,
    commit: bool = True,
) -> list:
    """Handle batch note creation/updates with version conflict resolution."""
    from schemas.sync import SyncPushResult

    results = []

    for note_sync in notes:
        try:
            if note_sync.core_id is None:
                # New note
                note_data = NoteCreate(
                    title=note_sync.title,
                    content=note_sync.content,
                    type=note_sync.type,
                    source_id=connected_app_id,
                    user_id=user_id,
                )
                db_note = Note(**note_data.model_dump())
                db_note.version = note_sync.version
                session.add(db_note)
                await session.flush()
                await session.refresh(db_note)

                results.append(
                    SyncPushResult(
                        core_id=db_note.id,
                        status="created",
                        server_version=db_note.version,
                    )
                )
                logger.info(
                    f"Created note via sync: id={db_note.id}, version={db_note.version}"
                )

            else:
                # Update existing note by core_id
                result = await session.execute(
                    select(Note).where(
                        Note.id == note_sync.core_id,
                        Note.user_id == user_id,
                    )
                )
                db_note = result.scalar_one_or_none()

                if not db_note:
                    results.append(
                        SyncPushResult(
                            core_id=note_sync.core_id,
                            status="rejected",
                            server_version=None,
                        )
                    )
                    continue

                # Version conflict resolution: higher version wins
                if note_sync.version < db_note.version:
                    # Server version is newer, reject update
                    results.append(
                        SyncPushResult(
                            core_id=note_sync.core_id,
                            status="rejected",
                            server_version=db_note.version,
                        )
                    )
                    logger.info(
                        f"Rejected note update: core_id={note_sync.core_id}, app_version={note_sync.version}, server_version={db_note.version}"
                    )
                elif note_sync.version > db_note.version:
                    # App version is newer, accept update
                    if note_sync.is_deleted:
                        db_note.is_deleted = True
                        db_note.version = note_sync.version
                    else:
                        db_note.title = note_sync.title
                        db_note.content = note_sync.content
                        db_note.type = note_sync.type
                        db_note.version = note_sync.version
                    await session.flush()

                    results.append(
                        SyncPushResult(
                            core_id=db_note.id,
                            status="updated",
                            server_version=db_note.version,
                        )
                    )
                    logger.info(
                        f"Updated note via sync: id={db_note.id}, version={db_note.version}"
                    )
                else:
                    # Same version, check if content differs or is_deleted (optimistic locking)
                    if note_sync.is_deleted:
                        db_note.is_deleted = True
                        db_note.version = note_sync.version
                        await session.flush()
                        results.append(
                            SyncPushResult(
                                core_id=db_note.id,
                                status="updated",
                                server_version=db_note.version,
                            )
                        )
                        logger.info(
                            f"Soft-deleted note via sync: id={db_note.id}, version={db_note.version}"
                        )
                    elif (
                        db_note.title != note_sync.title
                        or db_note.content != note_sync.content
                        or db_note.type != note_sync.type
                    ):
                        # Content differs, accept update and increment version
                        db_note.title = note_sync.title
                        db_note.content = note_sync.content
                        db_note.type = note_sync.type
                        db_note.version += 1
                        await session.flush()

                        results.append(
                            SyncPushResult(
                                core_id=db_note.id,
                                status="updated",
                                server_version=db_note.version,
                            )
                        )
                        logger.info(
                            f"Updated note via sync (same version, content changed): id={db_note.id}, version={db_note.version}"
                        )
                    else:
                        # Same version, same content - no change needed
                        results.append(
                            SyncPushResult(
                                core_id=db_note.id,
                                status="updated",
                                server_version=db_note.version,
                            )
                        )

        except Exception as e:
            logger.error(f"Error syncing note: {e}", exc_info=True)
            results.append(
                SyncPushResult(
                    core_id=note_sync.core_id or 0,
                    status="rejected",
                    server_version=None,
                )
            )

    if commit:
        await session.commit()
    return results


async def get_notes_by_ids(
    session: AsyncSession,
    user_id: int,
    note_ids: list[int],
) -> list[Note]:
    """Fetch multiple notes by IDs."""
    if not note_ids:
        return []

    result = await session.execute(
        select(Note).where(
            Note.id.in_(note_ids),
            Note.user_id == user_id,
        )
    )
    return list(result.scalars().all())


# ----- Categories -----


async def compare_categories(
    session: AsyncSession,
    user_id: int,
    app_categories: list[CategoryVersion],
) -> "CategoriesCompareResult":
    from schemas.sync import CategoriesCompareResult

    core_ids_from_request = {c.core_id for c in app_categories if c.core_id is not None}
    app_versions_by_core_id = {c.core_id: c.version for c in app_categories if c.core_id is not None}

    if not app_categories:
        r = await session.execute(select(Category).where(Category.user_id == user_id))
        all_cats = {c.id: c for c in r.scalars().all()}
        return CategoriesCompareResult(
            to_pull=[
                CategoryVersion(core_id=i, version=c.version, is_deleted=c.is_deleted)
                for i, c in all_cats.items()
                if not c.is_deleted
            ],
            to_push=[],
        )

    server_cats = {}
    if core_ids_from_request:
        r = await session.execute(
            select(Category).where(Category.id.in_(core_ids_from_request), Category.user_id == user_id)
        )
        server_cats = {c.id: c for c in r.scalars().all()}
    r = await session.execute(select(Category).where(Category.user_id == user_id))
    all_cats = {c.id: c for c in r.scalars().all()}

    missing_on_server, outdated_on_server, missing_on_app, outdated_on_app = [], [], [], []
    for c in app_categories:
        core_id = c.core_id
        if core_id is not None:
            if core_id not in server_cats:
                if not c.is_deleted:
                    missing_on_server.append(c)
            elif app_versions_by_core_id.get(core_id, 0) > server_cats[core_id].version:
                outdated_on_server.append(c)
        else:
            if not c.is_deleted:
                missing_on_server.append(
                    CategoryVersion(
                        app_id=c.app_id,
                        core_id=None,
                        version=c.version or 1,
                        is_deleted=False,
                    )
                )

    for i, c in all_cats.items():
        if i not in core_ids_from_request:
            if not c.is_deleted:
                missing_on_app.append(
                    CategoryVersion(core_id=i, version=c.version, is_deleted=c.is_deleted)
                )
        elif i in server_cats and app_versions_by_core_id.get(i, 0) < c.version:
            outdated_on_app.append(
                CategoryVersion(core_id=i, version=c.version, is_deleted=c.is_deleted)
            )

    return CategoriesCompareResult(
        to_pull=missing_on_app + outdated_on_app,
        to_push=missing_on_server + outdated_on_server,
    )


async def sync_categories(
    session: AsyncSession,
    user_id: int,
    categories: list["CategorySync"],
    *,
    commit: bool = True,
) -> list["SyncCategoryPushResult"]:
    from schemas.sync import CategorySync, SyncCategoryPushResult

    results = []
    for s in categories:
        try:
            if s.core_id is None:
                db = Category(
                    user_id=user_id,
                    name=s.name,
                    version=s.version,
                    is_deleted=s.is_deleted,
                )
                session.add(db)
                await session.flush()
                await session.refresh(db)
                results.append(
                    SyncCategoryPushResult(
                        core_id=db.id,
                        status="created",
                        server_version=db.version,
                    )
                )
            else:
                r = await session.execute(
                    select(Category).where(
                        Category.id == s.core_id, Category.user_id == user_id
                    )
                )
                db = r.scalar_one_or_none()
                if not db:
                    results.append(
                        SyncCategoryPushResult(
                            core_id=s.core_id,
                            status="rejected",
                            server_version=None,
                        )
                    )
                    continue
                if s.version < db.version:
                    results.append(
                        SyncCategoryPushResult(
                            core_id=s.core_id,
                            status="rejected",
                            server_version=db.version,
                        )
                    )
                elif s.version > db.version or s.is_deleted:
                    db.name = s.name if not s.is_deleted else db.name
                    db.is_deleted = s.is_deleted
                    db.version = s.version
                    await session.flush()
                    results.append(
                        SyncCategoryPushResult(
                            core_id=db.id,
                            status="updated",
                            server_version=db.version,
                        )
                    )
                else:
                    db.name = s.name
                    db.version += 1
                    await session.flush()
                    results.append(
                        SyncCategoryPushResult(
                            core_id=db.id,
                            status="updated",
                            server_version=db.version,
                        )
                    )
        except Exception as e:
            logger.error(f"Error syncing category: {e}", exc_info=True)
            results.append(
                SyncCategoryPushResult(
                    core_id=s.core_id or 0,
                    status="rejected",
                    server_version=None,
                )
            )
    if commit:
        await session.commit()
    return results


async def get_categories_by_ids(
    session: AsyncSession,
    user_id: int,
    category_ids: list[int],
) -> list[Category]:
    if not category_ids:
        return []
    r = await session.execute(
        select(Category).where(Category.id.in_(category_ids), Category.user_id == user_id)
    )
    return list(r.scalars().all())


# ----- Relationships (scope: both notes belong to user) -----


async def _user_note_ids(session: AsyncSession, user_id: int) -> set[int]:
    r = await session.execute(select(Note.id).where(Note.user_id == user_id))
    return {row[0] for row in r.all()}


async def compare_relationships(
    session: AsyncSession,
    user_id: int,
    app_relationships: list[RelationshipVersion],
) -> "RelationshipsCompareResult":
    from schemas.sync import RelationshipsCompareResult

    user_notes = await _user_note_ids(session, user_id)
    app_keys = {(r.note_a_core_id, r.note_b_core_id) for r in app_relationships}
    app_versions = {
        (r.note_a_core_id, r.note_b_core_id): r.version
        for r in app_relationships
    }

    r = await session.execute(select(Relationship))
    all_rels = [
        x
        for x in r.scalars().all()
        if x.note_a_id in user_notes and x.note_b_id in user_notes
    ]
    server_map = {(rel.note_a_id, rel.note_b_id): rel for rel in all_rels}

    if not app_keys:
        return RelationshipsCompareResult(
            to_pull=[
                RelationshipVersion(
                    note_a_core_id=a,
                    note_b_core_id=b,
                    version=rel.version,
                    is_deleted=rel.is_deleted,
                )
                for (a, b), rel in server_map.items()
                if not rel.is_deleted
            ],
            to_push=[],
        )

    missing_on_server, outdated_on_server, missing_on_app, outdated_on_app = [], [], [], []
    for r in app_relationships:
        k = (r.note_a_core_id, r.note_b_core_id)
        if k not in server_map:
            if not r.is_deleted:
                missing_on_server.append(r)
        elif app_versions.get(k, 0) > server_map[k].version:
            outdated_on_server.append(r)
    for (a, b), rel in server_map.items():
        if (a, b) not in app_keys:
            if not rel.is_deleted:
                missing_on_app.append(
                    RelationshipVersion(
                        note_a_core_id=a,
                        note_b_core_id=b,
                        version=rel.version,
                        is_deleted=rel.is_deleted,
                    )
                )
        elif app_versions.get((a, b), 0) < rel.version:
            outdated_on_app.append(
                RelationshipVersion(
                    note_a_core_id=a,
                    note_b_core_id=b,
                    version=rel.version,
                    is_deleted=rel.is_deleted,
                )
            )

    return RelationshipsCompareResult(
        to_pull=missing_on_app + outdated_on_app,
        to_push=missing_on_server + outdated_on_server,
    )


async def sync_relationships(
    session: AsyncSession,
    user_id: int,
    relationships: list["RelationshipSync"],
    *,
    commit: bool = True,
) -> list["SyncRelationshipPushResult"]:
    from schemas.sync import RelationshipSync, SyncRelationshipPushResult

    user_notes = await _user_note_ids(session, user_id)
    results = []
    for s in relationships:
        try:
            if (
                s.note_a_core_id not in user_notes
                or s.note_b_core_id not in user_notes
            ):
                results.append(
                    SyncRelationshipPushResult(
                        note_a_core_id=s.note_a_core_id,
                        note_b_core_id=s.note_b_core_id,
                        status="rejected",
                        server_version=None,
                    )
                )
                continue
            r = await session.execute(
                select(Relationship).where(
                    Relationship.note_a_id == s.note_a_core_id,
                    Relationship.note_b_id == s.note_b_core_id,
                )
            )
            db = r.scalar_one_or_none()
            if not db:
                db = Relationship(
                    note_a_id=s.note_a_core_id,
                    note_b_id=s.note_b_core_id,
                    type=s.type,
                    version=s.version,
                    is_deleted=s.is_deleted,
                )
                session.add(db)
                await session.flush()
                await session.refresh(db)
                results.append(
                    SyncRelationshipPushResult(
                        note_a_core_id=db.note_a_id,
                        note_b_core_id=db.note_b_id,
                        status="created",
                        server_version=db.version,
                    )
                )
            else:
                if s.version < db.version:
                    results.append(
                        SyncRelationshipPushResult(
                            note_a_core_id=s.note_a_core_id,
                            note_b_core_id=s.note_b_core_id,
                            status="rejected",
                            server_version=db.version,
                        )
                    )
                else:
                    db.type = s.type
                    db.is_deleted = s.is_deleted
                    db.version = s.version
                    await session.flush()
                    results.append(
                        SyncRelationshipPushResult(
                            note_a_core_id=db.note_a_id,
                            note_b_core_id=db.note_b_id,
                            status="updated",
                            server_version=db.version,
                        )
                    )
        except Exception as e:
            logger.error(f"Error syncing relationship: {e}", exc_info=True)
            results.append(
                SyncRelationshipPushResult(
                    note_a_core_id=s.note_a_core_id,
                    note_b_core_id=s.note_b_core_id,
                    status="rejected",
                    server_version=None,
                )
            )
    if commit:
        await session.commit()
    return results


async def get_relationships_by_keys(
    session: AsyncSession,
    user_id: int,
    keys: list[tuple[int, int]],
) -> list[Relationship]:
    if not keys:
        return []
    user_notes = await _user_note_ids(session, user_id)
    rels = []
    for (a, b) in keys:
        if a not in user_notes or b not in user_notes:
            continue
        r = await session.execute(
            select(Relationship).where(
                Relationship.note_a_id == a,
                Relationship.note_b_id == b,
            )
        )
        x = r.scalar_one_or_none()
        if x:
            rels.append(x)
    return rels


# ----- Chunks (scope: note belongs to user) -----


async def compare_chunks(
    session: AsyncSession,
    user_id: int,
    app_chunks: list[ChunkVersion],
) -> "ChunksCompareResult":
    from schemas.sync import ChunksCompareResult

    user_notes = await _user_note_ids(session, user_id)
    core_ids_from_request = {c.core_id for c in app_chunks if c.core_id is not None}
    app_versions_by_core_id = {c.core_id: c.version for c in app_chunks if c.core_id is not None}

    r = await session.execute(select(Chunk).where(Chunk.note_id.in_(user_notes)))
    all_chunks = {c.id: c for c in r.scalars().all()}

    if not app_chunks:
        return ChunksCompareResult(
            to_pull=[
                ChunkVersion(core_id=c.id, version=c.version, is_deleted=c.is_deleted)
                for c in all_chunks.values()
                if not c.is_deleted
            ],
            to_push=[],
        )

    server_chunks = {}
    if core_ids_from_request:
        r = await session.execute(select(Chunk).where(Chunk.id.in_(core_ids_from_request)))
        server_chunks = {c.id: c for c in r.scalars().all()}

    missing_on_server, outdated_on_server, missing_on_app, outdated_on_app = [], [], [], []
    for c in app_chunks:
        core_id = c.core_id
        if core_id is not None:
            if core_id not in server_chunks:
                if not c.is_deleted:
                    missing_on_server.append(c)
            elif server_chunks[core_id].note_id not in user_notes:
                continue
            elif app_versions_by_core_id.get(core_id, 0) > server_chunks[core_id].version:
                outdated_on_server.append(c)
        else:
            # No core_id: report as missing on server (read-only; app should push via sync_chunks).
            if not c.is_deleted:
                missing_on_server.append(
                    ChunkVersion(
                        app_id=c.app_id,
                        core_id=None,
                        note_core_id=c.note_core_id,
                        version=c.version or 1,
                        is_deleted=False,
                    )
                )

    for i, c in all_chunks.items():
        if i not in core_ids_from_request:
            if not c.is_deleted:
                missing_on_app.append(
                    ChunkVersion(core_id=i, version=c.version, is_deleted=c.is_deleted)
                )
        elif i in server_chunks and app_versions_by_core_id.get(i, 0) < c.version:
            outdated_on_app.append(
                ChunkVersion(core_id=i, version=c.version, is_deleted=c.is_deleted)
            )

    return ChunksCompareResult(
        to_pull=missing_on_app + outdated_on_app,
        to_push=missing_on_server + outdated_on_server,
    )


async def sync_chunks(
    session: AsyncSession,
    user_id: int,
    chunks: list["ChunkSync"],
    *,
    commit: bool = True,
) -> list["SyncChunkPushResult"]:
    from schemas.sync import ChunkSync, SyncChunkPushResult

    user_notes = await _user_note_ids(session, user_id)
    results = []
    for s in chunks:
        try:
            if s.note_core_id not in user_notes:
                results.append(
                    SyncChunkPushResult(
                        core_id=s.core_id or 0,
                        status="rejected",
                        server_version=None,
                    )
                )
                continue
            if s.core_id is None:
                db = Chunk(
                    note_id=s.note_core_id,
                    position_start=s.position_start,
                    position_end=s.position_end,
                    summary=s.summary,
                    embedding=s.embedding,
                    version=s.version,
                    is_deleted=s.is_deleted,
                )
                session.add(db)
                await session.flush()
                await session.refresh(db)
                results.append(
                    SyncChunkPushResult(
                        core_id=db.id,
                        status="created",
                        server_version=db.version,
                    )
                )
            else:
                r = await session.execute(
                    select(Chunk).where(Chunk.id == s.core_id)
                )
                db = r.scalar_one_or_none()
                if not db or db.note_id not in user_notes:
                    results.append(
                        SyncChunkPushResult(
                            core_id=s.core_id,
                            status="rejected",
                            server_version=None,
                        )
                    )
                    continue
                if s.version < db.version:
                    results.append(
                        SyncChunkPushResult(
                            core_id=s.core_id,
                            status="rejected",
                            server_version=db.version,
                        )
                    )
                else:
                    db.position_start = s.position_start
                    db.position_end = s.position_end
                    db.summary = s.summary
                    if s.embedding is not None:
                        db.embedding = s.embedding
                    db.is_deleted = s.is_deleted
                    db.version = s.version
                    await session.flush()
                    results.append(
                        SyncChunkPushResult(
                            core_id=db.id,
                            status="updated",
                            server_version=db.version,
                        )
                    )
        except Exception as e:
            logger.error(f"Error syncing chunk: {e}", exc_info=True)
            results.append(
                SyncChunkPushResult(
                    core_id=s.core_id or 0,
                    status="rejected",
                    server_version=None,
                )
            )
    if commit:
        await session.commit()
    return results


async def get_chunks_by_ids(
    session: AsyncSession,
    user_id: int,
    chunk_ids: list[int],
) -> list[Chunk]:
    if not chunk_ids:
        return []
    user_notes = await _user_note_ids(session, user_id)
    r = await session.execute(select(Chunk).where(Chunk.id.in_(chunk_ids)))
    chunks = list(r.scalars().all())
    return [c for c in chunks if c.note_id in user_notes]


# ----- NoteCategories (scope: note and category belong to user) -----


async def compare_note_categories(
    session: AsyncSession,
    user_id: int,
    app_note_categories: list[NoteCategoryVersion],
) -> "NoteCategoriesCompareResult":
    from schemas.sync import NoteCategoriesCompareResult

    user_notes = await _user_note_ids(session, user_id)
    r = await session.execute(select(Category).where(Category.user_id == user_id))
    user_cats = {c.id for c in r.scalars().all()}

    app_keys = {
        (nc.note_core_id, nc.category_core_id) for nc in app_note_categories
    }
    app_versions = {
        (nc.note_core_id, nc.category_core_id): nc.version
        for nc in app_note_categories
    }

    r = await session.execute(select(NoteCategory))
    all_nc = [
        x
        for x in r.scalars().all()
        if x.note_id in user_notes and x.category_id in user_cats
    ]
    server_map = {(nc.note_id, nc.category_id): nc for nc in all_nc}

    if not app_keys:
        return NoteCategoriesCompareResult(
            to_pull=[
                NoteCategoryVersion(
                    note_core_id=nid,
                    category_core_id=cid,
                    version=nc.version,
                    is_deleted=nc.is_deleted,
                )
                for (nid, cid), nc in server_map.items()
                if not nc.is_deleted
            ],
            to_push=[],
        )

    missing_on_server, outdated_on_server, missing_on_app, outdated_on_app = [], [], [], []
    for nc in app_note_categories:
        k = (nc.note_core_id, nc.category_core_id)
        if k not in server_map:
            if not nc.is_deleted:
                missing_on_server.append(nc)
        elif app_versions.get(k, 0) > server_map[k].version:
            outdated_on_server.append(nc)
    for (nid, cid), nc in server_map.items():
        if (nid, cid) not in app_keys:
            if not nc.is_deleted:
                missing_on_app.append(
                    NoteCategoryVersion(
                        note_core_id=nid,
                        category_core_id=cid,
                        version=nc.version,
                        is_deleted=nc.is_deleted,
                    )
                )
        elif app_versions.get((nid, cid), 0) < nc.version:
            outdated_on_app.append(
                NoteCategoryVersion(
                    note_core_id=nid,
                    category_core_id=cid,
                    version=nc.version,
                    is_deleted=nc.is_deleted,
                )
            )

    return NoteCategoriesCompareResult(
        to_pull=missing_on_app + outdated_on_app,
        to_push=missing_on_server + outdated_on_server,
    )


async def sync_note_categories(
    session: AsyncSession,
    user_id: int,
    note_categories: list["NoteCategorySync"],
    *,
    commit: bool = True,
) -> list["SyncNoteCategoryPushResult"]:
    from schemas.sync import NoteCategorySync, SyncNoteCategoryPushResult

    user_notes = await _user_note_ids(session, user_id)
    r = await session.execute(select(Category).where(Category.user_id == user_id))
    user_cats = {c.id for c in r.scalars().all()}
    results = []
    for s in note_categories:
        try:
            if (
                s.note_core_id not in user_notes
                or s.category_core_id not in user_cats
            ):
                results.append(
                    SyncNoteCategoryPushResult(
                        note_core_id=s.note_core_id,
                        category_core_id=s.category_core_id,
                        status="rejected",
                        server_version=None,
                    )
                )
                continue
            r = await session.execute(
                select(NoteCategory).where(
                    NoteCategory.note_id == s.note_core_id,
                    NoteCategory.category_id == s.category_core_id,
                )
            )
            db = r.scalar_one_or_none()
            if not db:
                db = NoteCategory(
                    note_id=s.note_core_id,
                    category_id=s.category_core_id,
                    version=s.version,
                    is_deleted=s.is_deleted,
                )
                session.add(db)
                await session.flush()
                await session.refresh(db)
                results.append(
                    SyncNoteCategoryPushResult(
                        note_core_id=db.note_id,
                        category_core_id=db.category_id,
                        status="created",
                        server_version=db.version,
                    )
                )
            else:
                if s.version < db.version:
                    results.append(
                        SyncNoteCategoryPushResult(
                            note_core_id=s.note_core_id,
                            category_core_id=s.category_core_id,
                            status="rejected",
                            server_version=db.version,
                        )
                    )
                else:
                    db.is_deleted = s.is_deleted
                    db.version = s.version
                    await session.flush()
                    results.append(
                        SyncNoteCategoryPushResult(
                            note_core_id=db.note_id,
                            category_core_id=db.category_id,
                            status="updated",
                            server_version=db.version,
                        )
                    )
        except Exception as e:
            logger.error(f"Error syncing note_category: {e}", exc_info=True)
            results.append(
                SyncNoteCategoryPushResult(
                    note_core_id=s.note_core_id,
                    category_core_id=s.category_core_id,
                    status="rejected",
                    server_version=None,
                )
            )
    if commit:
        await session.commit()
    return results


async def get_note_categories_by_keys(
    session: AsyncSession,
    user_id: int,
    keys: list[tuple[int, int]],
) -> list[NoteCategory]:
    if not keys:
        return []
    user_notes = await _user_note_ids(session, user_id)
    r = await session.execute(select(Category).where(Category.user_id == user_id))
    user_cats = {c.id for c in r.scalars().all()}
    out = []
    for (nid, cid) in keys:
        if nid not in user_notes or cid not in user_cats:
            continue
        r = await session.execute(
            select(NoteCategory).where(
                NoteCategory.note_id == nid,
                NoteCategory.category_id == cid,
            )
        )
        x = r.scalar_one_or_none()
        if x:
            out.append(x)
    return out


