"""Unit tests for MCP note response shaping."""

from flit_mcp.note_response import shape_note_dict


def test_shape_note_dict_metadata_omits_content():
    note = {
        "id": 1,
        "title": "Hello",
        "content": "Long body text here",
        "user_id": 1,
    }
    shaped = shape_note_dict(note, return_mode="metadata", snippet_chars=20)
    assert "content" not in shaped
    assert shaped["content_length"] == len("Long body text here")
    assert "snippet" in shaped
    assert len(shaped["snippet"]) <= 21  # 20 + ellipsis char


def test_shape_note_dict_snippet_truncates():
    note = {"id": 1, "title": "T", "content": "x" * 100}
    shaped = shape_note_dict(note, return_mode="snippet", snippet_chars=10)
    assert shaped["content"].endswith("…")
    assert len(shaped["content"]) <= 11


def test_shape_note_dict_full_with_max_chars():
    note = {"id": 1, "title": "T", "content": "abcdefghij"}
    shaped = shape_note_dict(note, return_mode="full", max_content_chars=5)
    assert shaped["content"] == "abcde…"
