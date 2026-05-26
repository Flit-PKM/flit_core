"""Tests for path-scoped MCP CORS (reflect Origin on /mcp only)."""

from __future__ import annotations

import pytest
from fastapi import status

from config import settings
from middleware.cors import is_mcp_cors_path

pytest_plugins = ["test_mcp"]


def test_is_mcp_cors_path():
    assert is_mcp_cors_path("/mcp")
    assert is_mcp_cors_path("/mcp/oauth/token")
    assert is_mcp_cors_path("/.well-known/oauth-authorization-server")
    assert is_mcp_cors_path("/.well-known/oauth-protected-resource/mcp")
    assert not is_mcp_cors_path("/api/health")
    assert not is_mcp_cors_path("/api/notes")


@pytest.mark.parametrize(
    "origin",
    [
        "http://127.0.0.1:6274",
        "https://example-mcp-client.example",
    ],
)
def test_mcp_options_reflects_origin(mcp_enabled, test_client, origin):
    response = test_client.options(
        "/mcp",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization, content-type",
        },
    )
    assert response.status_code == status.HTTP_200_OK
    assert response.headers.get("access-control-allow-origin") == origin
    assert response.headers.get("access-control-allow-credentials") == "true"


def test_well_known_oauth_options_reflects_origin(mcp_enabled, test_client):
    origin = "http://localhost:9999"
    response = test_client.options(
        "/.well-known/oauth-authorization-server",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == status.HTTP_200_OK
    assert response.headers.get("access-control-allow-origin") == origin


def test_api_options_not_in_mcp_cors_allowlist(test_client):
    """Non-MCP routes stay on CORS_ORIGINS only (default localhost:5173)."""
    response = test_client.options(
        "/api/health",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.headers.get("access-control-allow-origin") != "https://evil.example"


def test_mcp_cors_reflect_disabled_uses_strict_cors(mcp_enabled, test_client, monkeypatch):
    monkeypatch.setattr(settings, "MCP_CORS_REFLECT_ORIGIN", False)
    # Origin must not be in CORS_ORIGINS (CORSMiddleware allowlist is fixed at app import).
    origin = "https://browser-mcp-not-in-allowlist.example"
    response = test_client.options(
        "/mcp",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.headers.get("access-control-allow-origin") != origin
