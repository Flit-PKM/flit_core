from __future__ import annotations

from typing import Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from models.note import NoteType
from models.relationship import RelationshipType
from schemas.category import CategoryRead
from schemas.chunk import ChunkRead
from schemas.note import NoteRead
from schemas.note_category import NoteCategoryRead
from schemas.relationship import RelationshipRead


def _require_app_id_or_core_id(values: dict) -> dict:
    """Ensure at least one of app_id or core_id is set."""
    if values.get("app_id") is None and values.get("core_id") is None:
        raise ValueError("At least one of app_id or core_id must be set")
    return values


def _as_dict_for_validator(data: Union[dict, object]) -> dict:
    """Normalize validator input to dict."""
    if isinstance(data, dict):
        return data
    if hasattr(data, "model_dump"):
        return data.model_dump()
    return dict(data)


class NoteVersion(BaseModel):
    app_id: Optional[Union[int, str]] = Field(
        None,
        description="App's local id (e.g. UUID or int). Either app_id or core_id required.",
    )
    core_id: Optional[int] = Field(
        None,
        description="Server/DB id (same as Note.id). Either app_id or core_id required.",
    )
    version: int = Field(..., description="Note version number", examples=[1, 2, 5])
    is_deleted: bool = Field(
        False,
        description="If true, entity is soft-deleted on this side (compare omits from missing_* when deleted)",
    )

    @model_validator(mode="before")
    @classmethod
    def require_app_id_or_core_id(cls, data: Union[dict, object]) -> dict:
        return _require_app_id_or_core_id(_as_dict_for_validator(data))


class CategoryVersion(BaseModel):
    app_id: Optional[Union[int, str]] = Field(
        None,
        description="App's local id. Either app_id or core_id required.",
    )
    core_id: Optional[int] = Field(
        None,
        description="Server/DB id (same as Category.id). Either app_id or core_id required.",
    )
    version: int = Field(..., description="Category version number", examples=[1, 2])
    is_deleted: bool = Field(
        False,
        description="If true, entity is soft-deleted on this side (compare omits from missing_* when deleted)",
    )

    @model_validator(mode="before")
    @classmethod
    def require_app_id_or_core_id(cls, data: Union[dict, object]) -> dict:
        return _require_app_id_or_core_id(_as_dict_for_validator(data))


class RelationshipVersion(BaseModel):
    note_a_core_id: int = Field(
        ...,
        description="First note core_id (server ID)",
        examples=[1, 42],
    )
    note_b_core_id: int = Field(
        ...,
        description="Second note core_id (server ID)",
        examples=[2, 43],
    )
    version: int = Field(..., description="Relationship version number", examples=[1, 2])
    is_deleted: bool = Field(
        False,
        description="If true, entity is soft-deleted on this side (compare omits from missing_* when deleted)",
    )


class ChunkVersion(BaseModel):
    app_id: Optional[Union[int, str]] = Field(
        None,
        description="App's local id. Either app_id or core_id required.",
    )
    core_id: Optional[int] = Field(
        None,
        description="Server/DB id (same as Chunk.id). Either app_id or core_id required.",
    )
    note_core_id: Optional[int] = Field(
        None,
        description="Note's server id; required when creating placeholder chunk (core_id missing, not is_deleted).",
    )
    version: int = Field(..., description="Chunk version number", examples=[1, 2])
    is_deleted: bool = Field(
        False,
        description="If true, entity is soft-deleted on this side (compare omits from missing_* when deleted)",
    )

    @model_validator(mode="before")
    @classmethod
    def require_app_id_or_core_id(cls, data: Union[dict, object]) -> dict:
        return _require_app_id_or_core_id(_as_dict_for_validator(data))


class NoteCategoryVersion(BaseModel):
    note_core_id: int = Field(
        ...,
        description="Note core_id (server ID)",
        examples=[1, 42],
    )
    category_core_id: int = Field(
        ...,
        description="Category core_id (server ID)",
        examples=[1, 5],
    )
    version: int = Field(..., description="NoteCategory version number", examples=[1, 2])
    is_deleted: bool = Field(
        False,
        description="If true, entity is soft-deleted on this side (compare omits from missing_* when deleted)",
    )


class NotesCompareResult(BaseModel):
    to_pull: list[NoteVersion] = Field(
        default_factory=list,
        description="Entities outdated or missing on the app; app should GET these by core_id.",
    )
    to_push: list[NoteVersion] = Field(
        default_factory=list,
        description="Entities outdated or missing on the server; app should POST these. Excludes hard-removed (missing + is_deleted).",
    )


class CategoriesCompareResult(BaseModel):
    to_pull: list[CategoryVersion] = Field(
        default_factory=list,
        description="Entities outdated or missing on the app; app should GET these by core_id.",
    )
    to_push: list[CategoryVersion] = Field(
        default_factory=list,
        description="Entities outdated or missing on the server; app should POST these. Excludes hard-removed (missing + is_deleted).",
    )


class RelationshipsCompareResult(BaseModel):
    to_pull: list[RelationshipVersion] = Field(
        default_factory=list,
        description="Entities outdated or missing on the app; app should GET these by (note_a_core_id, note_b_core_id).",
    )
    to_push: list[RelationshipVersion] = Field(
        default_factory=list,
        description="Entities outdated or missing on the server; app should POST these. Excludes hard-removed (missing + is_deleted).",
    )


class ChunksCompareResult(BaseModel):
    to_pull: list[ChunkVersion] = Field(
        default_factory=list,
        description="Entities outdated or missing on the app; app should GET these by core_id.",
    )
    to_push: list[ChunkVersion] = Field(
        default_factory=list,
        description="Entities outdated or missing on the server; app should POST these. Excludes hard-removed (missing + is_deleted).",
    )


class NoteCategoriesCompareResult(BaseModel):
    to_pull: list[NoteCategoryVersion] = Field(
        default_factory=list,
        description="Entities outdated or missing on the app; app should GET these by (note_core_id, category_core_id).",
    )
    to_push: list[NoteCategoryVersion] = Field(
        default_factory=list,
        description="Entities outdated or missing on the server; app should POST these. Excludes hard-removed (missing + is_deleted).",
    )


# ----- Per-table compare requests -----


class CompareNotesRequest(BaseModel):
    notes: list[NoteVersion] = Field(
        default_factory=list,
        description="Note IDs and versions from the app to compare with server",
    )


class CompareCategoriesRequest(BaseModel):
    categories: list[CategoryVersion] = Field(
        default_factory=list,
        description="Category IDs and versions from the app",
    )


class CompareRelationshipsRequest(BaseModel):
    relationships: list[RelationshipVersion] = Field(
        default_factory=list,
        description="Relationship (note_a_core_id, note_b_core_id) and versions from the app",
    )


class CompareChunksRequest(BaseModel):
    chunks: list[ChunkVersion] = Field(
        default_factory=list,
        description="Chunk IDs and versions from the app",
    )


class CompareNoteCategoriesRequest(BaseModel):
    note_categories: list[NoteCategoryVersion] = Field(
        default_factory=list,
        description="Note_category (note_core_id, category_core_id) and versions from the app",
    )


class NoteSync(BaseModel):
    core_id: Optional[int] = Field(
        None,
        description="Server/DB id (core_id). None = create; set = update. Push body is DB-only (no app_id).",
        examples=[1, None],
    )
    title: str = Field(
        ...,
        min_length=1,
        description="Note title",
        examples=["Meeting Notes", "Project Ideas"]
    )
    content: str = Field(
        ...,
        min_length=1,
        description="Note content/body text",
        examples=["This is the note content..."]
    )
    type: NoteType = Field(
        default=NoteType.BASE,
        description="Type of note: BASE (default), INSIGHT, or SUMMARY",
        examples=[NoteType.BASE, NoteType.INSIGHT]
    )
    version: int = Field(
        ...,
        ge=1,
        description="Note version number (must be >= 1)",
        examples=[1, 2, 5]
    )
    is_deleted: bool = Field(
        False,
        description="If true, marks the note as soft-deleted (server stores only is_deleted and version for sync)",
    )


class CategorySync(BaseModel):
    core_id: Optional[int] = Field(
        None,
        description="Server/DB id (core_id). None = create; set = update. Push uses only core_id.",
        examples=[1, None],
    )
    name: str = Field(..., min_length=1, description="Category name", examples=["Work"])
    version: int = Field(..., ge=1, description="Category version", examples=[1, 2])
    is_deleted: bool = Field(False, description="If true, marks the category as soft-deleted")


class RelationshipSync(BaseModel):
    note_a_core_id: int = Field(
        ...,
        description="First note core_id (server ID)",
        examples=[1],
    )
    note_b_core_id: int = Field(
        ...,
        description="Second note core_id (server ID)",
        examples=[2],
    )
    type: RelationshipType = Field(..., description="Relationship type")
    version: int = Field(..., ge=1, description="Relationship version", examples=[1, 2])
    is_deleted: bool = Field(False, description="If true, marks the relationship as soft-deleted")


class ChunkSync(BaseModel):
    core_id: Optional[int] = Field(
        None,
        description="Server/DB id (core_id). None = create; set = update. Push uses only core_id.",
        examples=[1, None],
    )
    note_core_id: int = Field(
        ...,
        description="Note core_id this chunk belongs to (server ID)",
        examples=[1],
    )
    position_start: int = Field(..., ge=0, description="Start position", examples=[0])
    position_end: int = Field(..., ge=0, description="End position", examples=[100])
    summary: str = Field(..., min_length=1, description="Chunk summary", examples=["Summary"])
    embedding: Optional[list[float]] = Field(None, description="Vector embedding (optional)")
    version: int = Field(..., ge=1, description="Chunk version", examples=[1, 2])
    is_deleted: bool = Field(False, description="If true, marks the chunk as soft-deleted")


class NoteCategorySync(BaseModel):
    note_core_id: int = Field(
        ...,
        description="Note core_id (server ID)",
        examples=[1],
    )
    category_core_id: int = Field(
        ...,
        description="Category core_id (server ID)",
        examples=[1],
    )
    version: int = Field(..., ge=1, description="NoteCategory version", examples=[1, 2])
    is_deleted: bool = Field(False, description="If true, marks the link as soft-deleted")


# ----- Sync GET response shapes (use *_core_id naming) -----


class SyncNoteRead(NoteRead):
    """Note payload for sync GET; exposes id as core_id."""

    id: int = Field(..., serialization_alias="core_id")


class SyncCategoryRead(CategoryRead):
    """Category payload for sync GET; exposes id as core_id."""

    id: int = Field(..., serialization_alias="core_id")


class SyncChunkRead(ChunkRead):
    """Chunk payload for sync GET; exposes id as core_id, note_id as note_core_id."""

    id: int = Field(..., serialization_alias="core_id")
    note_id: int = Field(..., serialization_alias="note_core_id")


class SyncRelationshipRead(RelationshipRead):
    """Relationship payload for sync GET; exposes note_a_id/note_b_id as *_core_id."""

    note_a_id: int = Field(..., serialization_alias="note_a_core_id")
    note_b_id: int = Field(..., serialization_alias="note_b_core_id")


class SyncNoteCategoryRead(NoteCategoryRead):
    """NoteCategory payload for sync GET; exposes note_id/category_id as *_core_id."""

    note_id: int = Field(..., serialization_alias="note_core_id")
    category_id: int = Field(..., serialization_alias="category_core_id")


# ----- Per-table push result types -----


class SyncPushResult(BaseModel):
    core_id: int = Field(
        ...,
        description="core_id of the note that was processed (same as Note.id)",
        examples=[1, 42],
    )
    status: str = Field(
        ...,
        description="Sync status: 'created', 'updated', or 'rejected'",
        examples=["created", "updated", "rejected"],
    )
    server_version: Optional[int] = Field(None, examples=[2, 5, None])


class SyncCategoryPushResult(BaseModel):
    core_id: int = Field(...)
    status: str = Field(...)
    server_version: Optional[int] = Field(None)


class SyncRelationshipPushResult(BaseModel):
    note_a_core_id: int = Field(...)
    note_b_core_id: int = Field(...)
    status: str = Field(...)
    server_version: Optional[int] = Field(None)


class SyncChunkPushResult(BaseModel):
    core_id: int = Field(...)
    status: str = Field(...)
    server_version: Optional[int] = Field(None)


class SyncNoteCategoryPushResult(BaseModel):
    note_core_id: int = Field(...)
    category_core_id: int = Field(...)
    status: str = Field(...)
    server_version: Optional[int] = Field(None)


class SyncNotesResponse(BaseModel):
    note: dict = Field(
        ...,
        description="Single note object (using NoteRead schema structure)",
    )


class SyncCategoriesResponse(BaseModel):
    category: dict = Field(
        ...,
        description="Single category object (CategoryRead shape)",
    )


class SyncRelationshipsResponse(BaseModel):
    relationship: dict = Field(
        ...,
        description="Single relationship object (RelationshipRead shape)",
    )


class SyncChunksResponse(BaseModel):
    chunk: dict = Field(
        ...,
        description="Single chunk object (ChunkRead shape)",
    )


class SyncNoteCategoriesResponse(BaseModel):
    note_category: dict = Field(
        ...,
        description="Single NoteCategory object (NoteCategoryRead shape)",
    )
