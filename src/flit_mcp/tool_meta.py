"""Shared MCP tool metadata for catalog, OpenAPI, and search_tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from flit_mcp.server_info import MCP_MAX_BATCH_NOTE_IDS
from flit_mcp.tool_access import MCP_WRITE_TOOL_NAMES

ToolScope = Literal["read", "read write"]
ToolCategory = Literal[
    "notes",
    "categories",
    "relationships",
    "note_categories",
    "user",
    "discovery",
]


@dataclass(frozen=True)
class ToolExample:
    title: str
    input: dict[str, Any]
    output_summary: str


@dataclass(frozen=True)
class ToolMeta:
    category: ToolCategory
    tags: tuple[str, ...]
    short_description: str
    scopes: ToolScope
    examples: tuple[ToolExample, ...] = field(default_factory=tuple)


TOOL_META: dict[str, ToolMeta] = {
    "search_tools": ToolMeta(
        category="discovery",
        tags=("discovery", "meta", "search"),
        short_description=(
            "Find relevant MCP tools by keyword or natural language without loading full schemas."
        ),
        scopes="read",
        examples=(
            ToolExample(
                title="Find note creation tools",
                input={"query": "create a note", "limit": 5},
                output_summary="Ranked tool hits with name, category, tags, short_description, scopes",
            ),
        ),
    ),
    "list_notes": ToolMeta(
        category="notes",
        tags=("notes", "read", "search", "discovery"),
        short_description="Discover notes with search, filters, and pagination before fetching full content.",
        scopes="read",
        examples=(
            ToolExample(
                title="Lightweight discovery",
                input={"search": "project alpha", "return_mode": "metadata", "limit": 20},
                output_summary="List of note metadata dicts (no full content)",
            ),
        ),
    ),
    "get_note": ToolMeta(
        category="notes",
        tags=("notes", "read"),
        short_description="Fetch one owned note with categories and relationships.",
        scopes="read",
        examples=(
            ToolExample(
                title="Full note body",
                input={"note_id": 42, "return_mode": "full"},
                output_summary="NoteDetailRead-shaped dict with categories and relationships",
            ),
        ),
    ),
    "get_notes": ToolMeta(
        category="notes",
        tags=("notes", "read", "batch"),
        short_description=f"Batch-fetch up to {MCP_MAX_BATCH_NOTE_IDS} notes by id in one call.",
        scopes="read",
        examples=(
            ToolExample(
                title="Batch with snippets",
                input={
                    "note_ids": [1, 2, 3],
                    "return_mode": "snippet",
                    "include_categories": True,
                },
                output_summary='{"found": [...], "missing_ids": [...]}',
            ),
        ),
    ),
    "query_graph": ToolMeta(
        category="relationships",
        tags=("notes", "graph", "relationships", "read"),
        short_description="BFS traverse note relationships from a starting note (depth 1–3).",
        scopes="read",
        examples=(
            ToolExample(
                title="Flat graph snippet",
                input={
                    "starting_id": 42,
                    "max_depth": 2,
                    "return_mode": "snippet",
                    "return_format": "flat",
                },
                output_summary="flat: nodes + edges; or tree: nested root with children",
            ),
        ),
    ),
    "create_note": ToolMeta(
        category="notes",
        tags=("notes", "write", "create"),
        short_description="Create a new BASE note owned by the authenticated user.",
        scopes="read write",
        examples=(
            ToolExample(
                title="Capture a note",
                input={
                    "title": "Meeting log",
                    "content": "## 2026-07-24\nInitial context",
                    "pinned": False,
                },
                output_summary="Created NoteRead dict including id, title, content, timestamps",
            ),
        ),
    ),
    "update_note": ToolMeta(
        category="notes",
        tags=("notes", "write", "update"),
        short_description="Partial-update note fields; content replaces the full body when set.",
        scopes="read write",
        examples=(
            ToolExample(
                title="Rename only",
                input={"note_id": 42, "title": "Updated title"},
                output_summary="Updated NoteRead dict",
            ),
        ),
    ),
    "append_to_note": ToolMeta(
        category="notes",
        tags=("notes", "write", "append"),
        short_description="Append text to a note without replacing existing content.",
        scopes="read write",
        examples=(
            ToolExample(
                title="Incremental log",
                input={
                    "note_id": 42,
                    "content": "Decision: ship Phase 1 MCP improvements.",
                },
                output_summary="Updated NoteRead with concatenated content",
            ),
        ),
    ),
    "delete_note": ToolMeta(
        category="notes",
        tags=("notes", "write", "delete"),
        short_description="Soft-delete an owned note.",
        scopes="read write",
    ),
    "list_categories": ToolMeta(
        category="categories",
        tags=("categories", "read", "discovery"),
        short_description="List categories for organizing notes.",
        scopes="read",
    ),
    "get_category": ToolMeta(
        category="categories",
        tags=("categories", "read"),
        short_description="Fetch one category by id.",
        scopes="read",
    ),
    "create_category": ToolMeta(
        category="categories",
        tags=("categories", "write", "create"),
        short_description="Create a category for grouping notes.",
        scopes="read write",
        examples=(
            ToolExample(
                title="New category",
                input={"name": "Research"},
                output_summary="Created CategoryRead dict",
            ),
        ),
    ),
    "update_category": ToolMeta(
        category="categories",
        tags=("categories", "write", "update"),
        short_description="Rename an owned category.",
        scopes="read write",
    ),
    "delete_category": ToolMeta(
        category="categories",
        tags=("categories", "write", "delete"),
        short_description="Delete an owned category.",
        scopes="read write",
    ),
    "list_relationships": ToolMeta(
        category="relationships",
        tags=("relationships", "read"),
        short_description="List 1-hop relationships for a note.",
        scopes="read",
    ),
    "create_relationship": ToolMeta(
        category="relationships",
        tags=("relationships", "write", "create", "graph"),
        short_description="Link two owned notes with a typed relationship.",
        scopes="read write",
        examples=(
            ToolExample(
                title="Relate notes",
                input={
                    "note_a_id": 1,
                    "note_b_id": 2,
                    "type": "RELATED_TO",
                },
                output_summary="Created RelationshipRead dict",
            ),
        ),
    ),
    "delete_relationship": ToolMeta(
        category="relationships",
        tags=("relationships", "write", "delete"),
        short_description="Remove a relationship between two notes.",
        scopes="read write",
    ),
    "list_note_categories": ToolMeta(
        category="note_categories",
        tags=("notes", "categories", "read"),
        short_description="List categories linked to a note.",
        scopes="read",
    ),
    "link_note_to_category": ToolMeta(
        category="note_categories",
        tags=("notes", "categories", "write"),
        short_description="Attach a note to a category.",
        scopes="read write",
        examples=(
            ToolExample(
                title="Organize a note",
                input={"note_id": 42, "category_id": 7},
                output_summary="Created NoteCategoryRead link",
            ),
        ),
    ),
    "unlink_note_from_category": ToolMeta(
        category="note_categories",
        tags=("notes", "categories", "write"),
        short_description="Remove a note–category link.",
        scopes="read write",
    ),
    "get_user_profile": ToolMeta(
        category="user",
        tags=("user", "read", "entitlement"),
        short_description="Return the authenticated user's profile and entitlement summary.",
        scopes="read",
    ),
}

# Stable group order for catalog consumers.
TOOL_GROUP_ORDER: tuple[ToolCategory, ...] = (
    "discovery",
    "notes",
    "categories",
    "relationships",
    "note_categories",
    "user",
)


def build_tool_groups(tool_names: list[str] | None = None) -> dict[str, list[str]]:
    """Map category -> tool names present in tool_names (or all known meta)."""
    allowed = set(tool_names) if tool_names is not None else set(TOOL_META)
    groups: dict[str, list[str]] = {cat: [] for cat in TOOL_GROUP_ORDER}
    for name, meta in TOOL_META.items():
        if name in allowed:
            groups[meta.category].append(name)
    return {k: v for k, v in groups.items() if v}


def tool_scope_for(name: str) -> ToolScope:
    meta = TOOL_META.get(name)
    if meta:
        return meta.scopes
    return "read write" if name in MCP_WRITE_TOOL_NAMES else "read"


def search_tool_metas(
    query: str,
    *,
    group: str | None = None,
    limit: int = 10,
    allow_write: bool = True,
    descriptions: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Rank tools by keyword overlap; return lightweight discovery hits."""
    tokens = [t for t in query.lower().split() if t]
    if not tokens:
        return []

    limit = min(max(limit, 1), 50)
    hits: list[tuple[int, str, ToolMeta]] = []

    for name, meta in TOOL_META.items():
        if not allow_write and meta.scopes == "read write":
            continue
        if group and meta.category != group:
            continue

        haystack_parts = [
            name.replace("_", " "),
            meta.category,
            meta.short_description,
            " ".join(meta.tags),
            (descriptions or {}).get(name, ""),
        ]
        haystack = " ".join(haystack_parts).lower()

        score = 0
        for token in tokens:
            if token == name or token == name.replace("_", ""):
                score += 10
            elif token in name:
                score += 6
            if token in meta.tags:
                score += 5
            if token == meta.category:
                score += 4
            if token in haystack:
                score += 2
        if score > 0:
            hits.append((score, name, meta))

    hits.sort(key=lambda item: (-item[0], item[1]))
    results: list[dict[str, Any]] = []
    for _score, name, meta in hits[:limit]:
        results.append(
            {
                "name": name,
                "category": meta.category,
                "tags": list(meta.tags),
                "short_description": meta.short_description,
                "scopes": meta.scopes,
            }
        )
    return results
