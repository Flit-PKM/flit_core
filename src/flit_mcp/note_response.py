"""Shape note payloads for MCP tools (token-efficient content controls)."""

from __future__ import annotations

from typing import Any, Literal

ReturnMode = Literal["full", "metadata", "snippet"]

DEFAULT_LIST_SNIPPET_CHARS = 500


def _truncate(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[:max_chars] + "…"


def make_snippet(title: str, content: str, max_chars: int) -> str:
    """Build a short excerpt from title and content."""
    combined = f"{title}\n{content}".strip()
    return _truncate(combined, max_chars)


def shape_note_dict(
    note_dict: dict[str, Any],
    *,
    return_mode: ReturnMode = "full",
    max_content_chars: int | None = None,
    snippet_chars: int = DEFAULT_LIST_SNIPPET_CHARS,
) -> dict[str, Any]:
    """Apply return_mode and content length limits to a serialized note dict."""
    content = note_dict.get("content") or ""
    note_dict = dict(note_dict)
    note_dict["content_length"] = len(content)

    if return_mode == "metadata":
        note_dict.pop("content", None)
        note_dict["snippet"] = make_snippet(
            note_dict.get("title") or "",
            content,
            snippet_chars,
        )
        return note_dict

    if return_mode == "snippet":
        limit = max_content_chars if max_content_chars is not None else snippet_chars
        note_dict["content"] = make_snippet(
            note_dict.get("title") or "",
            content,
            limit,
        )
        return note_dict

    # full
    if max_content_chars is not None:
        note_dict["content"] = _truncate(content, max_content_chars)
    return note_dict


def shape_note_detail_dict(
    detail_dict: dict[str, Any],
    *,
    return_mode: ReturnMode = "full",
    max_content_chars: int | None = None,
    snippet_chars: int = DEFAULT_LIST_SNIPPET_CHARS,
) -> dict[str, Any]:
    """Shape a NoteDetailRead dict (includes categories/relationships)."""
    return shape_note_dict(
        detail_dict,
        return_mode=return_mode,
        max_content_chars=max_content_chars,
        snippet_chars=snippet_chars,
    )


def normalize_return_mode(value: str) -> ReturnMode:
    if value not in ("full", "metadata", "snippet"):
        from exceptions import ValidationError

        raise ValidationError(
            "return_mode must be one of: full, metadata, snippet"
        )
    return value  # type: ignore[return-value]
