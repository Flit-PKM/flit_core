from __future__ import annotations

READ_SCOPE = "read"
WRITE_SCOPE = "write"
READ_WRITE_SCOPE = "read write"

SUPPORTED_SCOPES = frozenset({READ_SCOPE, READ_WRITE_SCOPE})


def normalize_requested_scope(scope: str | None) -> str:
    """Map OAuth scope parameter to stored scope string."""
    if not scope or not scope.strip():
        return READ_SCOPE
    raw = scope.strip()
    if raw == READ_WRITE_SCOPE or "write" in raw.split():
        return READ_WRITE_SCOPE
    return READ_SCOPE


def parse_scopes(scopes: str) -> set[str]:
    parts = {p.strip() for p in scopes.split() if p.strip()}
    if READ_WRITE_SCOPE.replace(" ", "") in scopes.replace(" ", "") or (
        READ_SCOPE in parts and WRITE_SCOPE in parts
    ):
        return {READ_SCOPE, WRITE_SCOPE}
    if scopes.strip() == READ_WRITE_SCOPE:
        return {READ_SCOPE, WRITE_SCOPE}
    if WRITE_SCOPE in parts:
        return {READ_SCOPE, WRITE_SCOPE}
    return {READ_SCOPE} if READ_SCOPE in parts or not parts else parts


def scopes_allow_write(scopes: set[str]) -> bool:
    return WRITE_SCOPE in scopes


def scope_display_label(scope: str) -> str:
    """Human-readable label for OAuth consent UI."""
    if normalize_requested_scope(scope) == READ_WRITE_SCOPE:
        return "Read and write"
    return "Read only"


def scope_display_description(scope: str) -> str:
    if normalize_requested_scope(scope) == READ_WRITE_SCOPE:
        return "Create, update, and delete notes, categories, and relationships"
    return "List and read notes, categories, and relationships"
