# Flit Core

Backend API for **Flit** (PKM / personal knowledge management). FastAPI app with PostgreSQL, JWT auth, OAuth-style app connections, notes, categories, and sync.

## Requirements

- **Python** ≥ 3.14  
- **Database**: PostgreSQL (with pgvector for vector features) **or** Cloudflare D1 (serverless SQLite)  
- **[uv](https://docs.astral.sh/uv/)** (recommended) or pip

## Quick start

### 1. Clone and install

```bash
git clone <repo-url>
cd flit_core
uv sync
```

### 2. Environment

Copy the example env and set required values:

```bash
cp .env.example .env
```

Edit `.env` and set at least:

- **SECRET_KEY** – at least 32 characters (used for JWT)
- **Database**: either **PostgreSQL** (`DB_BACKEND=postgres` and either a single `DATABASE_URL` (e.g. for Render) or `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`, `DB_NAME`) or **Cloudflare D1** (`DB_BACKEND=d1` and `CF_ACCOUNT_ID`, `CF_API_TOKEN`, `CF_DATABASE_ID`)

See [Environment variables](#environment-variables) and [Cloudflare D1](#cloudflare-d1) for all options.

### 3. Database

Create the database (PostgreSQL or D1), then run migrations:

```bash
# From project root; Alembic uses .env for DB connection
uv run alembic upgrade head
```

With `DB_BACKEND=d1`, ensure `CF_ACCOUNT_ID`, `CF_API_TOKEN`, and `CF_DATABASE_ID` are set in `.env` before running migrations.

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
| Connected apps | `/connected-apps` | List/revoke connected apps |
| Apps | `/apps` | Allowed app list (e.g. Flit, Still) |
| Sync | `/sync` | Sync-related endpoints |
| Notes | `/notes` | Notes CRUD |
| Note categories | `/note-categories` | Note category links |
| Categories | `/categories` | Categories CRUD |
| Relationships | `/relationships` | Relationship CRUD |
| Subscriptions | `/subscriptions` | Subscribe (optional Cloudflare Turnstile) |
| MCP | `/mcp` | MCP server for agents (JSON-RPC tools + `flit://` resources; separate from `/api`) |
| MCP OAuth | `/mcp/oauth` | OAuth authorization server for MCP clients (when enabled) |
| MCP API keys | `/mcp/api-keys` | Create/list/revoke MCP API keys (uses main-app JWT; not under `/api`) |

### MCP OAuth for external clients

When `MCP_ENABLED=true`, MCP OAuth uses the same public URL as the rest of the API (`PUBLIC_BASE_URL`, or `http://127.0.0.1:8000` in development when unset):

1. Clients discover auth via `401` on `POST /mcp` (and `GET /mcp` for browser popups) and `/.well-known/oauth-protected-resource`.
2. Clients open `GET /mcp/oauth/authorize` (PKCE + `resource={public_url}/mcp`) for the Flit login and consent UI — **not** bare `GET /mcp` (that endpoint returns 401 or MCP metadata, not the login page). On the consent screen, users choose **read-only** or **read-write** access (the client’s `scope` query param only sets the default).
3. Clients exchange the code at `POST /mcp/oauth/token` and call `POST /mcp` with the Bearer token.

The OAuth login/consent pages use self-contained HTML/CSS under `src/flit_mcp/oauth/`. The Flit logo is vendored at `src/flit_mcp/oauth/static/flit_logo.svg` (copy from `webapp_build/images/flit_app_logo.svg` when the webapp logo changes).

Read-only tokens (`scope=read`) only expose read tools in MCP `tools/list`; write tools remain blocked on `tools/call` as well.

If a connector shows a **blank popup** and “authenticated” without a Flit login screen, check server logs: you should see `GET /mcp/oauth/authorize`. If you only see `GET /mcp` with **200** and HTML, the request was hitting the SPA before `legacy_sse` was enabled on the MCP router. After a correct connect, `POST /mcp` with a valid token should return tools via `tools/list`; an empty tool list means MCP Bearer auth never succeeded.

**Client registration:**

- **CIMD (recommended):** Host a JSON metadata document at an HTTPS URL and use that URL as `client_id`. The server advertises `client_id_metadata_document_supported: true` in `/.well-known/oauth-authorization-server`.
- **Pre-registered:** Set `MCP_OAUTH_STATIC_CLIENTS_JSON` with known `client_id` and `redirect_uris` for clients that do not support CIMD yet.
- **Dynamic Client Registration (opt-in):** Set `MCP_OAUTH_DCR_ENABLED=true`. New desktop clients open the browser to `GET /mcp/oauth/authorize` with `client_id=dynamic`, `client_name`, PKCE, and `redirect_uri` (no Flit login JWT in the app). After login and consent, the redirect includes `code`, `state`, and `client_id`; exchange at `POST /mcp/oauth/token`. Subscription (or access grant) is required at login when billing is configured. RFC 7591 clients may also call unauthenticated `POST /mcp/oauth/register` (advertised as `registration_endpoint` in metadata).

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

From project root (after `uv sync`). Tests use in-memory SQLite:

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
| **DB_BACKEND** | No | `postgres` (default) or `d1` (Cloudflare D1) |
| **DATABASE_URL** | When postgres | Full PostgreSQL URL (e.g. for Render). When set, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT, DB_NAME are optional. |
| **DB_USER** | When postgres | PostgreSQL user |
| **DB_PASSWORD** | When postgres | PostgreSQL password (min 8 chars) |
| **DB_HOST** | No | PostgreSQL host (default: `localhost`) |
| **DB_PORT** | No | PostgreSQL port (default: `5432`) |
| **DB_NAME** | When postgres | PostgreSQL database name |
| **CF_ACCOUNT_ID** | When d1 | Cloudflare account ID (D1) |
| **CF_API_TOKEN** | When d1 | Cloudflare API token with D1 permissions |
| **CF_DATABASE_ID** | When d1 | Cloudflare D1 database ID (UUID) |
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

- **Create a new revision:**  
  `uv run alembic revision --autogenerate -m "description"`  
  (Run from project root; Alembic adds `src` to the path automatically.)

- **Apply migrations:**  
  `uv run alembic upgrade head`

- **Downgrade one step:**  
  `uv run alembic downgrade -1`

Alembic reads the database URL from your `.env` (via `config.settings` in `alembic/env.py`). With `DB_BACKEND=d1` and CF_* set, migrations target D1 (SQLite-compatible DDL).

## Cloudflare D1

You can use **Cloudflare D1** (serverless SQLite) instead of PostgreSQL by setting:

- `DB_BACKEND=d1`
- `CF_ACCOUNT_ID` – your Cloudflare account ID  
- `CF_API_TOKEN` – API token with D1 permissions (e.g. Account:D1:Edit)  
- `CF_DATABASE_ID` – the D1 database UUID  

The app uses the [sqlalchemy-cloudflare-d1](https://pypi.org/project/sqlalchemy-cloudflare-d1/) dialect with async support (`cloudflare_d1+async://`).

**Limitations when using D1:**

- **No full transactions** – D1’s HTTP API auto-commits each statement; multi-statement transactions are not supported.
- **Rate limits** – Subject to Cloudflare API rate limits; consider retries/backoff in production.
- **No pgvector similarity** – Chunk embeddings are stored as JSON on D1; vector similarity search is only available with PostgreSQL.
- **Latency** – API-based access can add latency compared to a direct TCP connection.

Store `CF_API_TOKEN` securely (e.g. secrets manager); never hardcode.

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
