"""Notesearch: index and search non-encrypted notes by prefix/substring/fuzzy."""

from __future__ import annotations

import re
from datetime import datetime
from difflib import SequenceMatcher
from typing import List, Tuple

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

# Scoring weights (per matched query word, best tier wins for that word)
WEIGHT_PREFIX = 4.0
WEIGHT_SUBSTRING = 2.0
WEIGHT_FUZZY = 0.5
FUZZY_RATIO_THRESHOLD = 0.8

# Unicode word characters (letters, marks, digits, underscore in Unicode mode)
_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def _search_tokens(lower_text: str) -> List[str]:
    """Split lowercased text into word tokens; drop stopwords and underscore-only tokens."""
    words = _TOKEN_RE.findall(lower_text)
    return [
        w
        for w in words
        if w.strip("_") and w not in STOPWORDS
    ]


def normalize_for_search(title: str, content: str) -> str:
    """Build searchable text: title + content lowercased, tokenized, stopwords removed."""
    combined = f"{title.lower()} {content.lower()}"
    return " ".join(_search_tokens(combined))


def _query_words(query: str) -> List[str]:
    """Normalize query into words, optionally dropping stopwords."""
    return _search_tokens(query.lower())


def _tier_for_query_word(
    qw: str, content_lower: str, note_words: List[str]
) -> str | None:
    """Best match tier for one query word: 'prefix', 'substring', 'fuzzy', or None."""
    for nw in note_words:
        if nw.startswith(qw) or qw.startswith(nw):
            return "prefix"
    if qw in content_lower:
        return "substring"
    best_ratio = 0.0
    for nw in note_words:
        if len(nw) < 2:
            continue
        r = SequenceMatcher(None, qw, nw).ratio()
        if r > best_ratio:
            best_ratio = r
    if best_ratio >= FUZZY_RATIO_THRESHOLD:
        return "fuzzy"
    return None


def _rank_note(content: str, query_words: List[str]) -> Tuple[int, float] | None:
    """
    Return (prefix_hits, total_score) for ranking, or None if the note is excluded.

    For two or more query words, every word must match at least one tier (AND).
    For a single query word, exclusion means no tier matched.
    """
    if not content or not query_words:
        return None
    content_lower = content.lower()
    note_words = content_lower.split()
    prefix_hits = 0
    total_score = 0.0
    for qw in query_words:
        tier = _tier_for_query_word(qw, content_lower, note_words)
        if tier is None:
            return None
        if tier == "prefix":
            prefix_hits += 1
            total_score += WEIGHT_PREFIX
        elif tier == "substring":
            total_score += WEIGHT_SUBSTRING
        else:
            total_score += WEIGHT_FUZZY
    return (prefix_hits, total_score)


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
    pinned_only: bool = False,
    updated_after: datetime | None = None,
    updated_before: datetime | None = None,
) -> List[Note]:
    """
    Search non-encrypted notes by query.

    Multi-word queries require every word to match (prefix, substring, or fuzzy).
    Results sort by prefix hit count, then weighted score, then recency.
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
        if pinned_only:
            stmt = stmt.where(Note.pinned == True)
        if updated_after is not None:
            stmt = stmt.where(Note.updated_at >= updated_after)
        if updated_before is not None:
            stmt = stmt.where(Note.updated_at <= updated_before)
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
        select(NoteSearch.note_id, NoteSearch.content, Note.updated_at, Note.pinned)
        .join(Note, Note.id == NoteSearch.note_id)
        .where(
            NoteSearch.user_id == user_id,
            Note.user_id == user_id,
            Note.is_deleted == False,
        )
    )
    if pinned_only:
        stmt = stmt.where(Note.pinned == True)
    if updated_after is not None:
        stmt = stmt.where(Note.updated_at >= updated_after)
    if updated_before is not None:
        stmt = stmt.where(Note.updated_at <= updated_before)
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

    scored: List[Tuple[int, int, float, datetime | None]] = []
    for note_id, content, updated_at, _pinned in rows:
        rank = _rank_note(content, query_words)
        if rank is None:
            continue
        prefix_hits, total_score = rank
        scored.append((note_id, prefix_hits, total_score, updated_at))

    scored.sort(
        key=lambda x: (
            -x[1],
            -x[2],
            -(x[3].timestamp() if x[3] else 0.0),
        )
    )

    note_ids = [nid for nid, _, _, _ in scored[skip : skip + limit]]
    if not note_ids:
        return []

    # Load full Note objects in score order
    id_to_order = {nid: i for i, nid in enumerate(note_ids)}
    stmt = select(Note).where(Note.id.in_(note_ids))
    result = await session.execute(stmt)
    notes = list(result.scalars().all())
    notes.sort(key=lambda n: id_to_order[n.id])
    return notes
