"""Core OpenAPI augmentations: auth docs, tag descriptions, Bearer scheme."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

CORE_DESCRIPTION = """Flit PKM backend API.

## Authentication

1. **Register** (optional): `POST /api/auth/register` with JSON body.
2. **Login** for a JWT:
   - `POST /api/auth/login` — `application/x-www-form-urlencoded` (OAuth2 password flow; `username` is email).
   - `POST /api/auth/login-json` — `application/json` with `email` and `password`.
   - `POST /api/auth/login-google` — Google ID token.
3. Response shape: `{"access_token": "<jwt>", "token_type": "bearer"}`.
4. Call protected routes with header: `Authorization: Bearer <access_token>`.

**Connected apps / sync** use OAuth access tokens from `POST /api/connect/exchange` (same Bearer header).
**MCP** (when enabled) accepts MCP OAuth tokens or user API keys (`flit_mcp_…`).

## Getting started

```bash
# Login (JSON)
curl -s -X POST http://localhost:8000/api/auth/login-json \\
  -H 'Content-Type: application/json' \\
  -d '{"email":"you@example.com","password":"your-password"}'

# List notes (replace TOKEN)
curl -s http://localhost:8000/api/notes \\
  -H "Authorization: Bearer TOKEN"
```

Click **Authorize** in Swagger UI and paste the JWT for protected `/api/*` routes.
"""

HTTP_BEARER_DESCRIPTION = (
    "Bearer token: JWT from POST /api/auth/login or /api/auth/login-json; "
    "OAuth access token from POST /api/connect/exchange (sync); "
    "or MCP OAuth token / flit_mcp_ API key when MCP is enabled."
)

API_TAG_DESCRIPTIONS: dict[str, str] = {
    "authentication": "Register, login, logout; JWT issuance.",
    "user": "Current user profile and settings.",
    "users": "Superuser user administration.",
    "admin": "Superuser dashboard and newsletters.",
    "access-codes": "Beta/access code create, list, revoke, activate.",
    "notes": "PKM notes CRUD.",
    "categories": "Note categories CRUD.",
    "relationships": "Links between notes.",
    "note-categories": "Assign categories to notes.",
    "sync": "Connected-app sync (OAuth Bearer, core_id semantics).",
    "connect": "Request connection code and exchange for tokens.",
    "connected-apps": "Manage connected applications.",
    "oauth": "OAuth token refresh and revoke.",
    "verification": "Email verification send and confirm.",
    "password-reset": "Request and confirm password reset.",
    "feedback": "User feedback and admin responses.",
    "subscriptions": "Mailing list subscribe and unsubscribe.",
    "billing": "Plans, checkout, and subscription status.",
    "apps": "App catalog from config.",
    "health": "Liveness and readiness (DB probe).",
}


def augment_core_openapi(schema: dict[str, Any], app: FastAPI) -> None:
    """Add auth documentation, tag descriptions, and HTTPBearer scheme metadata."""
    del app  # reserved for future route introspection

    schema.setdefault("info", {})["description"] = CORE_DESCRIPTION.strip()

    components = schema.setdefault("components", {})
    security_schemes = components.setdefault("securitySchemes", {})
    existing = security_schemes.get("HTTPBearer") or {}
    security_schemes["HTTPBearer"] = {
        "type": "http",
        "scheme": "bearer",
        "description": HTTP_BEARER_DESCRIPTION,
        **{k: v for k, v in existing.items() if k not in ("type", "scheme", "description")},
    }

    tags = schema.setdefault("tags", [])
    tag_names = {t.get("name") for t in tags if isinstance(t, dict)}
    for name, description in API_TAG_DESCRIPTIONS.items():
        if name not in tag_names:
            tags.append({"name": name, "description": description})
