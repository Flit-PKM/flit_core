"""Internal hashes for note change detection (not exposed via API)."""

from __future__ import annotations

import hashlib

_RECORD_SEP = "\x1e"


def body_hash(*, title: str, content: str) -> str:
    """SHA-256 of title+content; used to skip body/notesearch writes when unchanged."""
    payload = _RECORD_SEP.join((title, content)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def compute_state_hash(*, title: str, content: str, pinned: bool, color: str) -> str:
    """SHA-256 of title, content, pinned, and color for noop detection."""
    payload = _RECORD_SEP.join(
        (title, content, str(pinned).lower(), color or "")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
