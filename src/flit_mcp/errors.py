"""Actionable MCP error messages."""

from __future__ import annotations

from exceptions import NotFoundError


def note_not_found(note_id: int) -> NotFoundError:
    return NotFoundError(
        f"Note {note_id} not found or access denied. Verify the ID via list_notes."
    )


def note_not_found_pair(note_id: int) -> NotFoundError:
    return NotFoundError(
        f"Note {note_id} not found or access denied. "
        "Verify note IDs via list_notes before linking."
    )
