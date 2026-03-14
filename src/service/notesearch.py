"""Notesearch: index and search non-encrypted notes by prefix/substring/fuzzy."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import List

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.category import Category
from models.note import Note
from models.note_category import NoteCategory
from models.notesearch import NoteSearch

# Small stopwords to remove from stored content and optionally from query
STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "at",
        "but",
        "for",
        "in",
        "is",
        "of",
        "on",
        "or",
        "the",
        "to",
        "which",
    }
)

# Scoring weights
WEIGHT_PREFIX = 2.0
WEIGHT_SUBSTRING = 1.0
WEIGHT_FUZZY = 0.3
FUZZY_RATIO_THRESHOLD = 0.8


def normalize_for_search(title: str, content: str) -> str:
    """Build searchable text: title + content lowercased, small stopwords removed."""
    combined = f"{title.lower()} {content.lower()}"
    words = re.findall(r"[a-z0-9]+", combined)
    return " ".join(w for w in words if w not in STOPWORDS and len(w) > 0)


def _query_words(query: str) -> List[str]:
    """Normalize query into words, optionally dropping stopwords."""
    words = re.findall(r"[a-z0-9]+", query.lower())
    return [w for w in words if w not in STOPWORDS and len(w) > 0]


def _score_content(content: str, query_words: List[str]) -> float:
    """Score one note's content against query words. Prefix > substring > fuzzy."""
    if not content or not query_words:
        return 0.0
    content_lower = content.lower()
    note_words = content_lower.split()
    score = 0.0
    for qw in query_words:
        # Prefix: query word is prefix of any note word
        for nw in note_words:
            if nw.startswith(qw) or qw.startswith(nw):
                score += WEIGHT_PREFIX
                break
        else:
            # Substring: query word appears anywhere in content
            if qw in content_lower:
                score += WEIGHT_SUBSTRING
            else:
                # Fuzzy: best ratio against any note word
                best_ratio = 0.0
                for nw in note_words:
                    if len(nw) < 2:
                        continue
                    r = SequenceMatcher(None, qw, nw).ratio()
                    if r > best_ratio:
                        best_ratio = r
                if best_ratio >= FUZZY_RATIO_THRESHOLD:
                    score += WEIGHT_FUZZY
    return score


async def upsert_notesearch(
    session: AsyncSession,
    note_id: int,
    user_id: int,
    title: str,
    content: str,
) -> None:
    """Insert or update notesearch row for a note. Call only for non-encrypted notes."""
    search_content = normalize_for_search(title, content)
    stmt = select(NoteSearch).where(NoteSearch.note_id == note_id)
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    if row:
        row.content = search_content
        row.user_id = user_id
    else:
        session.add(
            NoteSearch(note_id=note_id, user_id=user_id, content=search_content)
        )
    await session.flush()


async def delete_notesearch(session: AsyncSession, note_id: int) -> None:
    """Hard-delete notesearch row for a note (e.g. on note soft-delete)."""
    await session.execute(delete(NoteSearch).where(NoteSearch.note_id == note_id))
    await session.flush()


async def search_notes(
    session: AsyncSession,
    user_id: int,
    query: str,
    *,
    category_name: str | None = None,
    skip: int = 0,
    limit: int = 20,
) -> List[Note]:
    """
    Search non-encrypted notes by query. Returns notes sorted by score (prefix/substring/fuzzy) then recency.
    Only notes with a notesearch row are considered (i.e. non-encrypted).
    """
    query_words = _query_words(query)
    if not query_words:
        # No meaningful query: return recent notes (same as no-search path but limited to indexed notes)
        stmt = (
            select(Note)
            .join(NoteSearch, NoteSearch.note_id == Note.id)
            .where(
                NoteSearch.user_id == user_id,
                Note.user_id == user_id,
                Note.is_deleted == False,
            )
        )
        if category_name:
            stmt = (
                stmt.join(NoteCategory, NoteCategory.note_id == Note.id)
                .join(Category, Category.id == NoteCategory.category_id)
                .where(
                    Category.user_id == user_id,
                    Category.name == category_name,
                    Category.is_deleted == False,
                    NoteCategory.is_deleted == False,
                )
                .distinct()
            )
        stmt = (
            stmt.order_by(Note.updated_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await session.execute(stmt)
        return list(result.scalars().unique().all() if category_name else result.scalars().all())

    # Load candidates with notesearch content and updated_at
    stmt = (
        select(NoteSearch.note_id, NoteSearch.content, Note.updated_at)
        .join(Note, Note.id == NoteSearch.note_id)
        .where(
            NoteSearch.user_id == user_id,
            Note.user_id == user_id,
            Note.is_deleted == False,
        )
    )
    if category_name:
        stmt = (
            stmt.join(NoteCategory, NoteCategory.note_id == Note.id)
            .join(Category, Category.id == NoteCategory.category_id)
            .where(
                Category.user_id == user_id,
                Category.name == category_name,
                Category.is_deleted == False,
                NoteCategory.is_deleted == False,
            )
            .distinct()
        )
    result = await session.execute(stmt)
    rows = result.all()

    # Score and sort: only include notes with at least one match (score > 0)
    scored = [
        (note_id, _score_content(content, query_words), updated_at)
        for note_id, content, updated_at in rows
    ]
    scored = [(nid, s, u) for nid, s, u in scored if s > 0]
    scored.sort(
        key=lambda x: (
            -x[1],
            -(x[2].timestamp() if x[2] else 0),
        )
    )

    note_ids = [nid for nid, _, _ in scored[skip : skip + limit]]
    if not note_ids:
        return []

    # Load full Note objects in score order
    id_to_order = {nid: i for i, nid in enumerate(note_ids)}
    stmt = select(Note).where(Note.id.in_(note_ids))
    result = await session.execute(stmt)
    notes = list(result.scalars().all())
    notes.sort(key=lambda n: id_to_order[n.id])
    return notes
