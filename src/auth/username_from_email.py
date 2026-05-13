"""Derive a valid username from an email local part (same rules as registration)."""

from __future__ import annotations

import re


def derive_username_from_email(email: str) -> str:
    """Sanitize email local part into username (3–50 chars, alphanumeric, _, -)."""
    email_local = email.split("@")[0]
    username = re.sub(r"[^a-zA-Z0-9_-]", "", email_local)
    if len(username) < 3:
        username = (email_local[:47] + "123")[:50]
    return username[:50]
