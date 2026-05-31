"""Helpers for constructing Note rows in tests."""

from models.note import Note
from service.note_state_hash import compute_state_hash


def make_test_note(**kwargs) -> Note:
    """Build a Note with state_hash set (required for direct test inserts)."""
    note = Note(**kwargs)
    note.state_hash = compute_state_hash(
        title=note.title,
        content=note.content,
        pinned=bool(note.pinned),
        color=note.color or "",
    )
    return note
