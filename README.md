# Flit Core

Backend API for **Flit** (PKM / personal knowledge management). FastAPI app with PostgreSQL, JWT auth, OAuth-style app connections, notes, categories, and sync.

## Requirements

- **Python** ≥ 3.13  
- **Database**: PostgreSQL  
- **[uv](https://docs.astral.sh/uv/)** (recommended) or pip

## Quick start

### 1. Clone and install

```bash
git clone <repo-url>
cd flit_core
uv sync --extra dev
```

### 2. Environment

Copy the example env and set required values:

```bash
cp .env.example .env
```

Edit `.env` and set at least:

- **SECRET_KEY** – at least 32 characters (used for JWT)
- **Database**: **PostgreSQL** — either a single `DATABASE_URL` (e.g. for Render) or `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`, `DB_NAME`

See [Environment variables](#environment-variables) for all options.

### 3. Database

Create the PostgreSQL database, then run migrations:

```bash
# From project root; Alembic uses .env for DB connection
uv run alembic upgrade head
```

### 4. Run the server

From project root (after `uv sync`):

```bash
uv run python -m main
```

Or with uvicorn directly:

```bash
uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

App runs on **http://0.0.0.0:8000**.

API docs: **http://localhost:8000/docs**

## Project layout

```
flit_core/
├── alembic/           # Migrations (alembic upgrade head)
├── alembic.ini
├── pyproject.toml
├── src/
│   ├── main.py        # FastAPI app entry
│   ├── config.py      # Settings (pydantic-settings from .env)
│   ├── auth/          # JWT, password hashing
│   ├── database/      # Async engine and session
│   ├── models/        # SQLAlchemy models
│   ├── routes/        # API route modules
│   ├── schemas/       # Pydantic request/response
│   ├── service/       # Business logic
│   ├── middleware/
│   └── exceptions/
├── tests/             # Pytest (async, in-memory SQLite)
├── scripts/
└── .env.example
```

## API overview

| Area | Prefix | Description |
|------|--------|-------------|
| Auth | `/auth` | Register, login (form + JSON), JWT tokens |
| User | `/users` | Current user profile, update |
| Connect | `/connect` | Request code, exchange for OAuth-style tokens (app connection) |
| OAuth | `/oauth` | Token refresh, revoke |
| Connected apps | `/connected-apps` | List/revoke sync devices (Flit, Still — not MCP agents) |
| Apps | `/apps` | Allowed app list (e.g. Flit, Still) |
| Sync | `/sync` | Sync-related endpoints |
| Notes | `/notes` | Notes CRUD |
| Note categories | `/note-categories` | Note category links |
| Categories | `/categories` | Categories CRUD |
| Relationships | `/relationships` | Relationship CRUD |
| Subscriptions | `/subscriptions` | Subscribe/unsubscribe (Cloudflare Turnstile) |
| Feedback | `/feedback` | Public feedback (Turnstile); admin list/reply |
| MCP | `/mcp` | MCP server for agents (JSON-RPC tools + `flit://` resources; separate from `/api`) |
| MCP OAuth | `/mcp/oauth` | OAuth authorization server for MCP clients (when enabled) |
| MCP API keys | `/mcp/api-keys` | Create/list/revoke MCP API keys (uses main-app JWT; not under `/api`) |
| MCP connections | `/mcp/connections` | List/revoke MCP OAuth sessions (desktop agents; main-app JWT) |
| Billing | `/billing` | Dodo Payments plans, checkout, subscription, portal, webhooks |

### Dodo Payments billing

See [docs/billing-dodo.md](docs/billing-dodo.md) for environment variables, webhook setup, and API flow.

### MCP OAuth for external clients

See [docs/mcp-integration.md](docs/mcp-integration.md) for agent workflows, content controls, and tool reference.

When `MCP_ENABLED=true`, MCP OAuth uses the same public URL as the rest of the API (`PUBLIC_BASE_URL`, or `http://127.0.0.1:8000` in development when unset):

1. Clients discover auth via `401` on `POST /mcp` (and `GET /mcp` for browser popups) and `/.well-known/oauth-protected-resource`.
2. Clients open `GET /mcp/oauth/authorize` (PKCE + `resource={public_url}/mcp`) for the Flit login and consent UI — **not** bare `GET /mcp` (that endpoint returns 401 or MCP metadata, not the login page). On the consent screen, users choose **read-only** or **read-write** access (the client’s `scope` query param only sets the default).
3. Clients exchange the code at `POST /mcp/oauth/token` and call `POST /mcp` with the Bearer token.

The OAuth login/consent pages use self-contained HTML/CSS under `src/flit_mcp/oauth/`. The Flit logo is vendored at `src/flit_mcp/oauth/static/flit_logo.svg` (copy from `webapp_build/images/flit_app_logo.svg` when the webapp logo changes).

Read-only tokens (`scope=read`) only expose read tools in MCP `tools/list`; write tools remain blocked on `tools/call` as well.

**Entitlement (billing):** When Dodo billing is configured, **sync** (`/api/sync/*`) and **MCP usage** (`POST /mcp` with a valid API key or OAuth token) require an active plan subscription or a non-expired access-code grant. App pairing (`POST /api/connect/exchange`), MCP OAuth connect/token issuance, and creating MCP API keys (`POST /mcp/api-keys`) are allowed without entitlement; unentitled users are blocked when they actually sync or call MCP tools.

If a connector shows a **blank popup** and “authenticated” without a Flit login screen, check server logs: you should see `GET /mcp/oauth/authorize`. If you only see `GET /mcp` with **200** and HTML, the request was hitting the SPA before `legacy_sse` was enabled on the MCP router. After a correct connect, `POST /mcp` with a valid token should return tools via `tools/list`; an empty tool list means MCP Bearer auth never succeeded.

**Client registration:**

- **CIMD (recommended):** Host a JSON metadata document at an HTTPS URL and use that URL as `client_id`. The server advertises `client_id_metadata_document_supported: true` in `/.well-known/oauth-authorization-server`.
- **Pre-registered:** Set `MCP_OAUTH_STATIC_CLIENTS_JSON` with known `client_id` and `redirect_uris` for clients that do not support CIMD yet.
- **Dynamic Client Registration (opt-in):** Set `MCP_OAUTH_DCR_ENABLED=true`. New desktop clients open the browser to `GET /mcp/oauth/authorize` with `client_id=dynamic`, `client_name`, PKCE, and `redirect_uri` (no Flit login JWT in the app). After login and consent, the redirect includes `code`, `state`, and `client_id`; exchange at `POST /mcp/oauth/token`. RFC 7591 clients may also call unauthenticated `POST /mcp/oauth/register` (advertised as `registration_endpoint` in metadata).

**Manual verification:**

```bash
export PUBLIC_URL=https://core.flit-pkm.com  # same as PUBLIC_BASE_URL
curl -sS -D - -o /dev/null -X POST "$PUBLIC_URL/mcp" \
  -H "Content-Type: application/json" \
  -H "MCP-Protocol-Version: 2025-06-18" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"t","version":"1"}}}'
curl -sS -D - -o /dev/null "$PUBLIC_URL/mcp"  # expect 401 + WWW-Authenticate, not 200 HTML
curl -sS "$PUBLIC_URL/.well-known/oauth-authorization-server" | jq .
# issuer and authorization_endpoint must use the same host as PUBLIC_URL
```

API keys (`flit_mcp_…`) remain a fallback for clients that do not implement MCP OAuth.

**CORS and browser MCP clients:** `CORS_ORIGINS` applies to the Flit web app and `/api` routes only. When `MCP_ENABLED=true`, `MCP_CORS_REFLECT_ORIGIN` (default `true`) echoes the request `Origin` on `/mcp`, `/mcp/oauth/*`, and MCP OAuth `/.well-known/*` paths so you do not list every MCP Inspector port or hosted client domain. Access to MCP data still requires a valid OAuth Bearer token or API key; CORS is not authorization. Native/desktop MCP hosts call the API directly and are not blocked by `CORS_ORIGINS`. Set `MCP_CORS_REFLECT_ORIGIN=false` only if you intentionally disable browser MCP support.

## Tests

From project root (after `uv sync --extra dev`). Tests use in-memory SQLite:

```bash
uv run pytest tests -v
```

With coverage:

```bash
uv run pytest tests -v --cov=main --cov=auth --cov=database --cov=config --cov=exceptions --cov=middleware --cov=models --cov=routes --cov=schemas --cov=service --cov-report=term-missing
```

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| **SECRET_KEY** | Yes | JWT signing key (min 32 chars). Change from default in production. |
| **DATABASE_URL** | When postgres | Full PostgreSQL URL (e.g. for Render). When set, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT, DB_NAME are optional. |
| **DB_USER** | When postgres | PostgreSQL user |
| **DB_PASSWORD** | When postgres | PostgreSQL password (min 8 chars) |
| **DB_HOST** | No | PostgreSQL host (default: `localhost`) |
| **DB_PORT** | No | PostgreSQL port (default: `5432`) |
| **DB_NAME** | When postgres | PostgreSQL database name |
| **ENVIRONMENT** | No | `development` \| `production` \| `test` (default: `development`) |
| **PUBLIC_BASE_URL** | When production | Canonical public URL (email links, MCP OAuth). Defaults in dev/test if unset. |
| **LOG_LEVEL** | No | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| **CORS_ORIGINS** | No | Comma-separated origins for web app / `/api` (default: `http://localhost:5173`) |
| **MCP_CORS_REFLECT_ORIGIN** | No | When MCP enabled (default `true`), reflect `Origin` on MCP routes for browser clients |
| **ALLOWED_APPS_JSON** | No | JSON array of `{slug, name}` to override allowed apps |
| **CONNECTION_CODE_EXPIRE_MINUTES** | No | TTL for connect codes (default: 10) |
| **CONNECTION_CODE_LENGTH** | No | Code length (default: 8) |
| **TURNSTILE_SECRET** | No | Cloudflare Turnstile secret (required for `POST /subscriptions`) |
| **DB_POOL_SIZE**, **DB_MAX_OVERFLOW** | No | Connection pool settings |

See `.env.example` for the full list and defaults.

## Migrations

History was squashed to a baseline revision (`baseline_001`) plus follow-up revisions. For a **new empty database**, run `uv run alembic upgrade head`. For an **existing database** that already had the old migration chain applied (e.g. `add_admin_webhooks` in `alembic_version`), purge-stamp the baseline without running it, then upgrade:

```bash
uv run alembic stamp --purge baseline_001 && uv run alembic upgrade head
```

`--purge` is required: after the squash the old revision files are gone, so plain `stamp` fails with `Can't locate revision identified by 'add_admin_webhooks'`. Do **not** run `upgrade baseline_001` on a database that already has tables.

- **Create a new revision:**  
  `uv run alembic revision --autogenerate -m "description"`  
  (Run from project root; Alembic adds `src` to the path automatically.)

- **Apply migrations:**  
  `uv run alembic upgrade head`

- **Downgrade one step:**  
  `uv run alembic downgrade -1`

Alembic reads the database URL from your `.env` (via `config.settings` in `alembic/env.py`).

## Production

- **Run from project root:** `uv run python -m main` (listens on port 8000) or `uv run uvicorn main:app --host 0.0.0.0 --port 8000`. On Render and similar hosts, use the platform-injected shell `PORT` only in the start command (e.g. `--port $PORT`), not as an app settings variable. For multiple workers: `uv run uvicorn main:app --host 0.0.0.0 --port 8000 --workers N`, or run behind gunicorn with uvicorn workers.
- **Environment:** Set `ENVIRONMENT=production`, `PUBLIC_BASE_URL` (e.g. `https://core.flit-pkm.com`), `LOG_LEVEL=INFO`, a strong unique `SECRET_KEY`, and explicit `CORS_ORIGINS` for your frontend(s). Do not use default or example values for `SECRET_KEY` in production.
- **Ignored env vars:** `VERIFY_EMAIL_BASE_URL`, `MCP_OAUTH_ISSUER`, and a pydantic `PORT` setting are not read. Use `PUBLIC_BASE_URL` and the uvicorn/cli listen port instead.
- **Health check:** `GET /health` returns 200 when the app and database are reachable; it runs a lightweight DB probe. Use it for load balancer or orchestrator (e.g. Kubernetes) readiness/liveness probes. On DB failure it returns 503.
- **Security:** In production, 422 responses do not include the request body, and 500 responses return a generic message; details are logged server-side only.
- **Optional:** If your Postgres requires SSL, add a `DB_SSL_MODE` (or equivalent) config and pass it into the engine; document in `.env.example` if you add it.

## Scripts

- **scripts/purge_soft_deleted.py** – Purge soft-deleted rows older than `PURGE_SOFT_DELETED_AFTER_WEEKS` (run as needed or via cron).

## License

See repository license.
