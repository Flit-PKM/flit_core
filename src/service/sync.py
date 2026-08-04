"""Sync service: compare (read-only) and push (create/update) for notes, categories, relationships, note_categories.

Compare functions are read-only; they never create, update, or delete rows in the DB.
Compare returns to_pull (app should GET) and to_push (app should POST); hard-removed entities (missing + is_deleted) are omitted from to_push.
Compare and push paths share small version-map helpers; entity persistence stays local.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from logging_config import get_logger
from models.category import Category
from models.note import Note
from models.note_category import NoteCategory
from models.relationship import Relationship
from schemas.note import NoteCreate
from schemas.sync import (
    CategoryVersion,
    NoteCategoryVersion,
    NoteSync,
    NoteVersion,
    RelationshipVersion,
)
from service.note_persistence import insert_note as persistence_insert_note
from service.note_persistence import soft_delete_note as persistence_soft_delete_note
from service.note_persistence import update_note as persistence_update_note
from service.note_state_hash import body_hash, compute_state_hash
from service.relationship import soft_delete_relationships_for_note

logger = get_logger(__name__)


def _compare_core_id_entities(
    app_entities: list,
    server_entities: list,
    *,
    version_type,
    result_type,
):
    """Compare user-scoped entities identified by an optional core ID."""
    app_core_ids = {
        entity.core_id for entity in app_entities if entity.core_id is not None
    }
    app_versions = {
        entity.core_id: entity.version
        for entity in app_entities
        if entity.core_id is not None
    }
    server_by_id = {entity.id: entity for entity in server_entities}
    missing_on_server, outdated_on_server, missing_on_app, outdated_on_app = (
        [],
        [],
        [],
        [],
    )

    for app_entity in app_entities:
        if app_entity.core_id is None:
            if not app_entity.is_deleted:
                missing_on_server.append(
                    version_type(
                        app_id=app_entity.app_id,
                        core_id=None,
                        version=app_entity.version or 1,
                        is_deleted=False,
                    )
                )
        elif app_entity.core_id not in server_by_id:
            if not app_entity.is_deleted:
                missing_on_server.append(app_entity)
        elif app_entity.version > server_by_id[app_entity.core_id].version:
            outdated_on_server.append(app_entity)

    for core_id, server_entity in server_by_id.items():
        if core_id not in app_core_ids:
            if not server_entity.is_deleted:
                missing_on_app.append(
                    version_type(
                        core_id=core_id,
                        version=server_entity.version,
                        is_deleted=server_entity.is_deleted,
                    )
                )
        elif server_entity.version > app_versions.get(core_id, 0):
            outdated_on_app.append(
                version_type(
                    core_id=core_id,
                    version=server_entity.version,
                    is_deleted=server_entity.is_deleted,
                )
            )

    return result_type(
        to_pull=missing_on_app + outdated_on_app,
        to_push=missing_on_server + outdated_on_server,
    )


def _compare_keyed_entities(
    app_entities: list,
    server_by_key: dict,
    *,
    key,
    result_type,
    version_from_server,
):
    """Compare already user-scoped entities identified by a composite key."""
    app_keys = {key(entity) for entity in app_entities}
    app_versions = {key(entity): entity.version for entity in app_entities}
    missing_on_server, outdated_on_server, missing_on_app, outdated_on_app = (
        [],
        [],
        [],
        [],
    )

    for app_entity in app_entities:
        entity_key = key(app_entity)
        if entity_key not in server_by_key:
            if not app_entity.is_deleted:
                missing_on_server.append(app_entity)
        elif app_versions[entity_key] > server_by_key[entity_key].version:
            outdated_on_server.append(app_entity)

    for entity_key, server_entity in server_by_key.items():
        if entity_key not in app_keys:
            if not server_entity.is_deleted:
                missing_on_app.append(version_from_server(entity_key, server_entity))
        elif server_entity.version > app_versions[entity_key]:
            outdated_on_app.append(version_from_server(entity_key, server_entity))

    return result_type(
        to_pull=missing_on_app + outdated_on_app,
        to_push=missing_on_server + outdated_on_server,
    )


def _version_push_decision(app_version: int, server_version: int) -> str:
    """Return whether a pushed version loses, wins, or matches."""
    if app_version < server_version:
        return "reject"
    if app_version > server_version:
        return "update"
    return "same"


async def compare_notes(
    session: AsyncSession,
    user_id: int,
    connected_app_id: int,
    app_notes: list[NoteVersion],
):
    """Compare app's note list with server. Read-only: does not create placeholders; returns to_pull and to_push (to_push includes new app items with core_id=None)."""
    result = await session.execute(
        select(Note).where(Note.user_id == user_id)
    )
    from schemas.sync import NotesCompareResult

    return _compare_core_id_entities(
        app_notes,
        list(result.scalars().all()),
        version_type=NoteVersion,
        result_type=NotesCompareResult,
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
                    pinned=note_sync.pinned,
                    color=note_sync.color,
                    source_id=connected_app_id,
                    user_id=user_id,
                )
                dump = note_data.model_dump()
                db_note = Note(**dump)
                db_note.version = note_sync.version
                db_note.state_hash = compute_state_hash(
                    title=note_sync.title,
                    content=note_sync.content,
                    pinned=note_sync.pinned,
                    color=note_sync.color,
                )
                if note_sync.is_deleted:
                    db_note.is_deleted = True
                await persistence_insert_note(
                    session,
                    db_note,
                    plaintext_title=note_sync.title,
                    plaintext_content=note_sync.content,
                )

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

                decision = _version_push_decision(
                    note_sync.version, db_note.version
                )
                if decision == "reject":
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
                elif decision == "update":
                    # App version is newer, accept update
                    if note_sync.is_deleted:
                        await persistence_soft_delete_note(
                            session, db_note, version=note_sync.version
                        )
                        await soft_delete_relationships_for_note(session, db_note.id)
                    else:
                        sync_body_changed = body_hash(
                            title=note_sync.title, content=note_sync.content
                        ) != body_hash(title=db_note.title, content=db_note.content)
                        db_note.type = note_sync.type
                        db_note.pinned = note_sync.pinned
                        db_note.color = note_sync.color
                        if sync_body_changed:
                            db_note.title = note_sync.title
                            db_note.content = note_sync.content
                        db_note.state_hash = compute_state_hash(
                            title=note_sync.title,
                            content=note_sync.content,
                            pinned=note_sync.pinned,
                            color=note_sync.color,
                        )
                        db_note.version = note_sync.version
                        await persistence_update_note(
                            session,
                            db_note,
                            plaintext_title=note_sync.title,
                            plaintext_content=note_sync.content,
                            sync_notesearch=sync_body_changed,
                        )

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
                        await persistence_soft_delete_note(
                            session, db_note, version=note_sync.version
                        )
                        await soft_delete_relationships_for_note(session, db_note.id)
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
                    else:
                        sync_new_state = compute_state_hash(
                            title=note_sync.title,
                            content=note_sync.content,
                            pinned=note_sync.pinned,
                            color=note_sync.color,
                        )
                        sync_type_changed = note_sync.type != db_note.type
                        if sync_new_state != db_note.state_hash or sync_type_changed:
                            sync_body_changed = body_hash(
                                title=note_sync.title, content=note_sync.content
                            ) != body_hash(
                                title=db_note.title, content=db_note.content
                            )
                            db_note.type = note_sync.type
                            db_note.pinned = note_sync.pinned
                            db_note.color = note_sync.color
                            if sync_body_changed:
                                db_note.title = note_sync.title
                                db_note.content = note_sync.content
                            db_note.state_hash = sync_new_state
                            db_note.version += 1
                            await persistence_update_note(
                                session,
                                db_note,
                                plaintext_title=note_sync.title,
                                plaintext_content=note_sync.content,
                                sync_notesearch=sync_body_changed,
                            )

                            results.append(
                                SyncPushResult(
                                    core_id=db_note.id,
                                    status="updated",
                                    server_version=db_note.version,
                                )
                            )
                            logger.info(
                                f"Updated note via sync (same version, fields changed): id={db_note.id}, version={db_note.version}"
                            )
                        else:
                            # Same version, same state - no change needed
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

    r = await session.execute(select(Category).where(Category.user_id == user_id))
    return _compare_core_id_entities(
        app_categories,
        list(r.scalars().all()),
        version_type=CategoryVersion,
        result_type=CategoriesCompareResult,
    )


async def sync_categories(
    session: AsyncSession,
    user_id: int,
    categories: list["CategorySync"],
    *,
    commit: bool = True,
) -> list["SyncCategoryPushResult"]:
    from schemas.sync import SyncCategoryPushResult

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
                decision = _version_push_decision(s.version, db.version)
                if decision == "reject":
                    results.append(
                        SyncCategoryPushResult(
                            core_id=s.core_id,
                            status="rejected",
                            server_version=db.version,
                        )
                    )
                elif decision == "update" or s.is_deleted:
                    db.name = s.name if not s.is_deleted else db.name
                    if s.is_deleted:
                        db.is_deleted = True
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
                    if db.name == s.name:
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


async def _active_user_note_ids(session: AsyncSession, user_id: int) -> set[int]:
    r = await session.execute(
        select(Note.id).where(Note.user_id == user_id, Note.is_deleted == False)
    )
    return {row[0] for row in r.all()}


async def _active_user_category_ids(session: AsyncSession, user_id: int) -> set[int]:
    r = await session.execute(
        select(Category.id).where(
            Category.user_id == user_id,
            Category.is_deleted == False,
        )
    )
    return {row[0] for row in r.all()}


async def compare_relationships(
    session: AsyncSession,
    user_id: int,
    app_relationships: list[RelationshipVersion],
) -> "RelationshipsCompareResult":
    from schemas.sync import RelationshipsCompareResult

    user_notes = await _user_note_ids(session, user_id)
    if not user_notes:
        all_rels = []
    else:
        r = await session.execute(
            select(Relationship).where(
                Relationship.note_a_id.in_(user_notes),
                Relationship.note_b_id.in_(user_notes),
            )
        )
        all_rels = list(r.scalars().all())
    server_map = {(rel.note_a_id, rel.note_b_id): rel for rel in all_rels}

    return _compare_keyed_entities(
        app_relationships,
        server_map,
        key=lambda relationship: (
            relationship.note_a_core_id,
            relationship.note_b_core_id,
        ),
        result_type=RelationshipsCompareResult,
        version_from_server=lambda key, relationship: RelationshipVersion(
            note_a_core_id=key[0],
            note_b_core_id=key[1],
            version=relationship.version,
            is_deleted=relationship.is_deleted,
        ),
    )


async def sync_relationships(
    session: AsyncSession,
    user_id: int,
    relationships: list["RelationshipSync"],
    *,
    commit: bool = True,
) -> list["SyncRelationshipPushResult"]:
    from schemas.sync import SyncRelationshipPushResult

    active_notes = await _active_user_note_ids(session, user_id)
    results = []
    for s in relationships:
        try:
            if (
                s.note_a_core_id not in active_notes
                or s.note_b_core_id not in active_notes
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
                if _version_push_decision(s.version, db.version) == "reject":
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
                    if s.is_deleted:
                        db.is_deleted = True
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

    if not user_notes or not user_cats:
        all_nc = []
    else:
        r = await session.execute(
            select(NoteCategory).where(
                NoteCategory.note_id.in_(user_notes),
                NoteCategory.category_id.in_(user_cats),
            )
        )
        all_nc = list(r.scalars().all())
    server_map = {(nc.note_id, nc.category_id): nc for nc in all_nc}

    return _compare_keyed_entities(
        app_note_categories,
        server_map,
        key=lambda note_category: (
            note_category.note_core_id,
            note_category.category_core_id,
        ),
        result_type=NoteCategoriesCompareResult,
        version_from_server=lambda key, note_category: NoteCategoryVersion(
            note_core_id=key[0],
            category_core_id=key[1],
            version=note_category.version,
            is_deleted=note_category.is_deleted,
        ),
    )


async def sync_note_categories(
    session: AsyncSession,
    user_id: int,
    note_categories: list["NoteCategorySync"],
    *,
    commit: bool = True,
) -> list["SyncNoteCategoryPushResult"]:
    from schemas.sync import SyncNoteCategoryPushResult

    active_notes = await _active_user_note_ids(session, user_id)
    active_cats = await _active_user_category_ids(session, user_id)
    results = []
    for s in note_categories:
        try:
            if (
                s.note_core_id not in active_notes
                or s.category_core_id not in active_cats
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
                if _version_push_decision(s.version, db.version) == "reject":
                    results.append(
                        SyncNoteCategoryPushResult(
                            note_core_id=s.note_core_id,
                            category_core_id=s.category_core_id,
                            status="rejected",
                            server_version=db.version,
                        )
                    )
                else:
                    if s.is_deleted:
                        db.is_deleted = True
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


