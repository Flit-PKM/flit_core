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
uv run uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --reload
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
| **ENVIRONMENT** | No | `development` \| `staging` \| `production` \| `test` (default: `development`) |
| **LOG_LEVEL** | No | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| **CORS_ORIGINS** | No | Comma-separated origins (default: `http://localhost:5173`) |
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

- **Run from project root:** `uv run python -m main` or `uv run uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}`. For multiple workers: `uv run uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --workers N`, or run behind gunicorn with uvicorn workers.
- **Environment:** Set `ENVIRONMENT=production`, `LOG_LEVEL=INFO`, a strong unique `SECRET_KEY`, and explicit `CORS_ORIGINS` for your frontend(s). Do not use default or example values for `SECRET_KEY` in production.
- **Health check:** `GET /health` returns 200 when the app and database are reachable; it runs a lightweight DB probe. Use it for load balancer or orchestrator (e.g. Kubernetes) readiness/liveness probes. On DB failure it returns 503.
- **Security:** In production, 422 responses do not include the request body, and 500 responses return a generic message; details are logged server-side only.
- **Optional:** If your Postgres requires SSL, add a `DB_SSL_MODE` (or equivalent) config and pass it into the engine; document in `.env.example` if you add it.

## Scripts

- **scripts/purge_soft_deleted.py** – Purge soft-deleted rows older than `PURGE_SOFT_DELETED_AFTER_WEEKS` (run as needed or via cron).

## License

See repository license.
