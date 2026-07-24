"""Shared MCP server identity for protocol initialize and catalog."""

from __future__ import annotations

MCP_SERVER_NAME = "Flit Core MCP"
MCP_SERVER_VERSION = "0.2.0"
MCP_SERVER_DESCRIPTION = (
    "Privacy-first personal knowledge management MCP with notes, categories, "
    "graph relationships, and progressive tool discovery."
)
MCP_MAX_BATCH_NOTE_IDS = 50
MCP_RETURN_MODES = ("full", "metadata", "snippet")
