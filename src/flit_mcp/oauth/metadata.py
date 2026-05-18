from __future__ import annotations

from service.mcp_oauth import mcp_issuer


def oauth_protected_resource_metadata() -> dict:
    issuer = mcp_issuer()
    return {
        "resource": f"{issuer}/mcp",
        "authorization_servers": [issuer],
        "scopes_supported": ["read", "read write"],
        "bearer_methods_supported": ["header"],
    }


def oauth_authorization_server_metadata() -> dict:
    issuer = mcp_issuer()
    return {
        "issuer": issuer,
        "authorization_endpoint": f"{issuer}/mcp/oauth/authorize",
        "token_endpoint": f"{issuer}/mcp/oauth/token",
        "revocation_endpoint": f"{issuer}/mcp/oauth/revoke",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none", "client_secret_post"],
        "scopes_supported": ["read", "read write"],
    }
