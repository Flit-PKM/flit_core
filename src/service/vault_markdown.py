from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable

import yaml
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import BusinessLogicError
from logging_config import get_logger
from models.category import Category
from models.note import Note, NoteType
from models.note_category import NoteCategory
from models.relationship import Relationship, RelationshipType
from schemas.category import CategoryCreate
from schemas.note_category import NoteCategoryCreate
from schemas.vault_markdown import VaultMarkdownImportResult
from service.category import create_category
from service.note_category import get_note_category, link_note_category
from service.note_persistence import insert_note
from service.note_state_hash import compute_state_hash

logger = get_logger(__name__)

_ILLEGAL_FILENAME_CHARS = re.compile(r'[/\\:*?"<>|]')
_RELATIONSHIPS_HEADER = re.compile(r"^## Relationships\s*$", re.MULTILINE)
_RELATIONSHIP_LINE = re.compile(r"^\*\*(.+?)\*\*:\s*\[\[(.+?)\]\]\s*$")
_FRONTMATTER_BOUNDARY = re.compile(r"^---\s*$", re.MULTILINE)

_EXPORT_STATUS = "PUBLISHED"
_SYMMETRIC_TYPES = frozenset(
    {RelationshipType.SIMILAR_TO, RelationshipType.RELATED_TO}
)

_LABEL_TO_EDGE: dict[str, tuple[RelationshipType, bool]] = {
    "follows to": (RelationshipType.FOLLOWS_ON, False),
    "follows on": (RelationshipType.FOLLOWS_ON, False),
    "follows from": (RelationshipType.FOLLOWS_ON, True),
    "similar to": (RelationshipType.SIMILAR_TO, False),
    "contradicts": (RelationshipType.CONTRADICTS, False),
    "references": (RelationshipType.REFERENCES, False),
    "related to": (RelationshipType.RELATED_TO, False),
}

_EXPORT_LABELS: dict[RelationshipType, tuple[str, str]] = {
    RelationshipType.FOLLOWS_ON: ("Follows to", "Follows from"),
    RelationshipType.SIMILAR_TO: ("Similar To", "Similar To"),
    RelationshipType.CONTRADICTS: ("Contradicts", "Contradicts"),
    RelationshipType.REFERENCES: ("References", "References"),
    RelationshipType.RELATED_TO: ("Related To", "Related To"),
}


@dataclass
class ParsedRelationship:
    label: str
    target_link_key: str


@dataclass
class ParsedNote:
    link_key: str
    title: str
    body: str
    categories: list[str] = field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    status: str = _EXPORT_STATUS
    relationships: list[ParsedRelationship] = field(default_factory=list)


def make_link_key(title: str, note_id: int) -> str:
    """Stable handle for filenames and wikilink targets."""
    normalized = " ".join(title.strip().split())
    sanitized = _ILLEGAL_FILENAME_CHARS.sub("_", normalized)
    sanitized = sanitized.rstrip(". ")
    if not sanitized:
        sanitized = "note"
    if len(sanitized) > 80:
        sanitized = sanitized[:80]
    sanitized = sanitized.rstrip(". ")
    if not sanitized:
        sanitized = "note"
    return f"{sanitized}_{note_id}"


def _format_instant(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_timestamp(value: object, fallback: datetime) -> datetime:
    if value is None:
        return fallback
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000.0, tz=timezone.utc)
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit():
            return datetime.fromtimestamp(int(stripped) / 1000.0, tz=timezone.utc)
        try:
            parsed = datetime.fromisoformat(stripped.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            pass
    return fallback


def _parse_status(value: object) -> str:
    if not isinstance(value, str):
        return _EXPORT_STATUS
    upper = value.strip().upper()
    if upper in ("DRAFT", "PROCESSING", "PUBLISHED"):
        return upper
    return _EXPORT_STATUS


def _normalize_categories(raw: object) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        name = raw.strip()
        return [name] if name else []
    if isinstance(raw, list):
        names: list[str] = []
        for item in raw:
            if isinstance(item, str):
                name = item.strip()
                if name:
                    names.append(name)
        return names
    return []


def parse_markdown_note_file(text: str, link_key: str, *, import_time: datetime) -> ParsedNote:
    """Parse one note file per the Flit markdown contract."""
    fm_match = _FRONTMATTER_BOUNDARY.search(text)
    if fm_match and fm_match.start() == 0:
        second = _FRONTMATTER_BOUNDARY.search(text, fm_match.end())
        if second:
            fm_text = text[fm_match.end() : second.start()]
            remainder = text[second.end() :]
            meta = yaml.safe_load(fm_text) or {}
            if not isinstance(meta, dict):
                meta = {}
        else:
            meta = {}
            remainder = text
    else:
        meta = {}
        remainder = text

    title = ""
    if isinstance(meta.get("title"), str):
        title = meta.get("title", "").strip()

    categories = _normalize_categories(
        meta.get("categories") if "categories" in meta else meta.get("ategories")
    )

    created_at = _parse_timestamp(meta.get("created"), import_time)
    updated_raw = meta.get("updated")
    if updated_raw is None:
        updated_at = created_at
    else:
        updated_at = _parse_timestamp(updated_raw, created_at)

    status = _parse_status(meta.get("status"))

    rel_header = _RELATIONSHIPS_HEADER.search(remainder)
    if rel_header:
        body = remainder[: rel_header.start()]
        rel_section = remainder[rel_header.end() :]
    else:
        body = remainder
        rel_section = ""

    relationships: list[ParsedRelationship] = []
    for line in rel_section.splitlines():
        m = _RELATIONSHIP_LINE.match(line.strip())
        if not m:
            continue
        relationships.append(
            ParsedRelationship(
                label=m.group(1).strip(),
                target_link_key=m.group(2).strip(),
            )
        )

    return ParsedNote(
        link_key=link_key,
        title=title,
        body=body,
        categories=categories,
        created_at=created_at,
        updated_at=updated_at,
        status=status,
        relationships=relationships,
    )


def _render_frontmatter(
    title: str,
    category_names: list[str],
    created_at: datetime,
    updated_at: datetime,
) -> str:
    data: dict = {
        "title": title,
        "categories": category_names,
        "created": _format_instant(created_at),
        "updated": _format_instant(updated_at),
        "status": _EXPORT_STATUS,
    }
    return yaml.safe_dump(
        data,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    ).strip()


def _relationship_label(rel_type: RelationshipType, is_note_a: bool) -> str:
    labels = _EXPORT_LABELS[rel_type]
    return labels[0] if is_note_a else labels[1]


def render_note_markdown(
    note: Note,
    category_names: list[str],
    relationships: Iterable[tuple[str, str]],
) -> str:
    """Build one .md file: frontmatter, body, optional relationships block."""
    frontmatter = _render_frontmatter(
        note.title,
        category_names,
        note.created_at,
        note.updated_at,
    )
    parts = [f"---\n{frontmatter}\n---", note.content]
    rel_lines = list(relationships)
    if rel_lines:
        parts.append("## Relationships")
        for label, target_key in rel_lines:
            parts.append(f"**{label}**: [[{target_key}]]")
    return "\n".join(parts) + "\n"


def _zip_timestamp_name() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("flit-%Y%m%d_%H%M%S.zip")


def _is_ignored_zip_entry(name: str) -> bool:
    return name.startswith("__MACOSX/") or name == ".DS_Store" or name.endswith("/")


def _extract_zip_entries(data: bytes) -> list[tuple[str, str]]:
    """Return (link_key, text) for root .md files; validate archive layout."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise BusinessLogicError("unreadable input") from exc

    entries: list[tuple[str, str]] = []
    with zf:
        for info in zf.infolist():
            name = info.filename.replace("\\", "/")
            if info.is_dir() or _is_ignored_zip_entry(name):
                continue
            if "/" in name:
                raise BusinessLogicError("zip must contain only root .md")
            lower = name.lower()
            if not lower.endswith(".md"):
                raise BusinessLogicError("zip must contain only root .md")
            link_key = name[: -3]
            raw = zf.read(info)
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise BusinessLogicError("unreadable input") from exc
            entries.append((link_key, text))

    if not entries:
        raise BusinessLogicError("no markdown notes found")
    entries.sort(key=lambda item: item[0])
    return entries


def _extract_single_file(data: bytes, filename: str | None) -> list[tuple[str, str]]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BusinessLogicError("unreadable input") from exc
    stem = "imported"
    if filename:
        base = filename.replace("\\", "/").rsplit("/", 1)[-1]
        if base.lower().endswith(".md"):
            stem = base[:-3]
        elif "." in base:
            stem = base.rsplit(".", 1)[0]
        else:
            stem = base or stem
    return [(stem, text)]


def extract_note_files(
    data: bytes, *, filename: str | None = None
) -> list[tuple[str, str]]:
    if data[:2] == b"PK":
        return _extract_zip_entries(data)
    return _extract_single_file(data, filename)


async def _load_user_notes(session: AsyncSession, user_id: int) -> list[Note]:
    result = await session.execute(
        select(Note)
        .where(Note.user_id == user_id, Note.is_deleted == False)
        .order_by(Note.id)
    )
    return list(result.scalars().all())


async def _load_export_relationships(
    session: AsyncSession, note_ids: set[int]
) -> list[Relationship]:
    if not note_ids:
        return []
    result = await session.execute(
        select(Relationship).where(
            Relationship.is_deleted == False,
            or_(
                Relationship.note_a_id.in_(note_ids),
                Relationship.note_b_id.in_(note_ids),
            ),
        )
    )
    rels = list(result.scalars().all())
    return [
        r
        for r in rels
        if r.note_a_id in note_ids and r.note_b_id in note_ids
    ]


async def _categories_by_note(
    session: AsyncSession, note_ids: Iterable[int]
) -> dict[int, list[str]]:
    ids = list(note_ids)
    if not ids:
        return {}
    result = await session.execute(
        select(NoteCategory.note_id, Category.name)
        .join(Category, Category.id == NoteCategory.category_id)
        .where(
            NoteCategory.note_id.in_(ids),
            NoteCategory.is_deleted == False,
            Category.is_deleted == False,
        )
        .order_by(Category.name)
    )
    out: dict[int, list[str]] = {}
    for note_id, name in result.all():
        out.setdefault(note_id, []).append(name)
    return out


async def export_vault_markdown(
    session: AsyncSession, user_id: int
) -> tuple[bytes, str]:
    notes = await _load_user_notes(session, user_id)
    if not notes:
        raise BusinessLogicError("no notes to export")

    note_ids = {n.id for n in notes}
    link_by_id = {n.id: make_link_key(n.title, n.id) for n in notes}
    categories_by_note = await _categories_by_note(session, note_ids)
    all_rels = await _load_export_relationships(session, note_ids)

    rel_lines_by_note: dict[int, list[tuple[str, str]]] = {nid: [] for nid in note_ids}
    for rel in all_rels:
        label_a = _relationship_label(rel.type, True)
        label_b = _relationship_label(rel.type, False)
        rel_lines_by_note[rel.note_a_id].append(
            (label_a, link_by_id[rel.note_b_id])
        )
        rel_lines_by_note[rel.note_b_id].append(
            (label_b, link_by_id[rel.note_a_id])
        )

    zip_name = _zip_timestamp_name()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for note in notes:
            link_key = link_by_id[note.id]
            md = render_note_markdown(
                note,
                categories_by_note.get(note.id, []),
                rel_lines_by_note.get(note.id, []),
            )
            zf.writestr(f"{link_key}.md", md.encode("utf-8"))

    logger.info(
        "Vault markdown export: user_id=%s notes=%s", user_id, len(notes)
    )
    return buf.getvalue(), zip_name


async def _find_category_by_name(
    session: AsyncSession, user_id: int, name: str
) -> Category | None:
    result = await session.execute(
        select(Category).where(
            Category.user_id == user_id,
            Category.name == name,
            Category.is_deleted == False,
        )
    )
    return result.scalar_one_or_none()


async def _ensure_category_for_note(
    session: AsyncSession,
    user_id: int,
    note_id: int,
    category_name: str,
) -> None:
    category = await _find_category_by_name(session, user_id, category_name)
    if not category:
        category = await create_category(
            session, CategoryCreate(name=category_name), user_id
        )
    existing = await get_note_category(session, note_id, category.id)
    if not existing:
        await link_note_category(
            session,
            NoteCategoryCreate(note_id=note_id, category_id=category.id),
        )


def _resolve_label(label: str) -> tuple[RelationshipType, bool] | None:
    key = label.strip().lower()
    if key in _LABEL_TO_EDGE:
        return _LABEL_TO_EDGE[key]
    upper = label.strip().upper()
    try:
        rel_type = RelationshipType(upper)
        return rel_type, False
    except ValueError:
        return None


async def _relationship_exists(
    session: AsyncSession,
    note_a_id: int,
    note_b_id: int,
    rel_type: RelationshipType,
) -> bool:
    if rel_type in _SYMMETRIC_TYPES:
        clause = or_(
            and_(
                Relationship.note_a_id == note_a_id,
                Relationship.note_b_id == note_b_id,
            ),
            and_(
                Relationship.note_a_id == note_b_id,
                Relationship.note_b_id == note_a_id,
            ),
        )
    else:
        clause = and_(
            Relationship.note_a_id == note_a_id,
            Relationship.note_b_id == note_b_id,
        )
    result = await session.execute(
        select(Relationship.note_a_id).where(
            Relationship.type == rel_type,
            Relationship.is_deleted == False,
            clause,
        ).limit(1)
    )
    return result.scalar_one_or_none() is not None


async def import_vault_markdown(
    session: AsyncSession,
    user_id: int,
    data: bytes,
    *,
    filename: str | None = None,
) -> VaultMarkdownImportResult:
    import_time = datetime.now(timezone.utc)
    file_entries = extract_note_files(data, filename=filename)
    parsed = [
        parse_markdown_note_file(text, link_key, import_time=import_time)
        for link_key, text in file_entries
    ]
    if not parsed:
        raise BusinessLogicError("no markdown notes found")

    link_key_to_id: dict[str, int] = {}
    notes_imported = 0
    relationships_imported = 0
    relationships_skipped = 0

    for note_data in sorted(parsed, key=lambda p: p.link_key):
        title = note_data.title or note_data.link_key
        content = note_data.body
        if not content:
            content = " "

        note = Note(
            title=title,
            content=content,
            type=NoteType.BASE,
            user_id=user_id,
            version=1,
            is_deleted=False,
            pinned=False,
            color="",
            created_at=note_data.created_at or import_time,
            updated_at=note_data.updated_at or import_time,
        )
        note.state_hash = compute_state_hash(
            title=title,
            content=content,
            pinned=False,
            color="",
        )
        await insert_note(
            session,
            note,
            plaintext_title=title,
            plaintext_content=content,
        )
        link_key_to_id[note_data.link_key] = note.id
        notes_imported += 1

        for cat_name in note_data.categories:
            trimmed = cat_name.strip()
            if trimmed:
                await _ensure_category_for_note(
                    session, user_id, note.id, trimmed
                )

    for note_data in parsed:
        current_id = link_key_to_id.get(note_data.link_key)
        if current_id is None:
            continue
        for rel_line in note_data.relationships:
            resolved = _resolve_label(rel_line.label)
            if resolved is None:
                relationships_skipped += 1
                continue
            rel_type, swap = resolved
            target_id = link_key_to_id.get(rel_line.target_link_key)
            if target_id is None:
                relationships_skipped += 1
                continue
            if swap:
                note_a_id, note_b_id = target_id, current_id
            else:
                note_a_id, note_b_id = current_id, target_id
            if note_a_id == note_b_id:
                relationships_skipped += 1
                continue
            if await _relationship_exists(session, note_a_id, note_b_id, rel_type):
                relationships_skipped += 1
                continue
            session.add(
                Relationship(
                    note_a_id=note_a_id,
                    note_b_id=note_b_id,
                    type=rel_type,
                    version=1,
                    is_deleted=False,
                )
            )
            await session.flush()
            relationships_imported += 1

    logger.info(
        "Vault markdown import: user_id=%s notes=%s rels=%s skipped=%s",
        user_id,
        notes_imported,
        relationships_imported,
        relationships_skipped,
    )
    return VaultMarkdownImportResult(
        notes_imported=notes_imported,
        relationships_imported=relationships_imported,
        relationships_skipped=relationships_skipped,
    )
