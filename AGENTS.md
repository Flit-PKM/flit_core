# AGENTS.md — flit_core

## How to run and test

```bash
uv sync --extra dev
cp .env.example .env   # set SECRET_KEY + DB
uv run alembic upgrade head
uv run python -m main
uv run pytest tests -q
```

## Principles

- YAGNI; reuse existing helpers; no new deps if avoidable; deletion over abstraction.
- Ponytail ladder: understand the flow, then pick the first rung that holds.
- Mark deliberate ceilings with `ponytail:` (single-process cache, in-memory rate limit, Python-side search).
- Clean breaks over legacy shims; when breaking, say what to wipe/reconfigure.
- Single-process assumptions are real today (plans cache, MCP rate limit, email cooldowns).

## Architecture map

| Layer | Path | Role |
|-------|------|------|
| Bootstrap | `src/main.py` | App, middleware, routers, SPA |
| Config | `src/config.py` | pydantic-settings |
| Auth | `src/auth/` | Login JWT, passwords, deps |
| Routes | `src/routes/` | HTTP `/api/*` |
| Services | `src/service/` | Business logic |
| Models/schemas | `src/models/`, `src/schemas/` | ORM + Pydantic |
| MCP | `src/flit_mcp/` | MCP tools, OAuth AS, middleware helpers |
| Migrations | `alembic/` | Schema history |
| Tests | `tests/` | Async pytest + in-memory SQLite |

God modules (extend carefully / split when touching): `service/sync.py`, `service/billing.py`, `service/mcp_oauth.py`, `flit_mcp/tools/pkm.py`.

## Gotchas

- Login JWT `sub` is **email**; OAuth/MCP token `sub` is **user_id** — do not mix deps.
- Connected-app OAuth access tokens require an active DB row (not JWT-only).
- Sync note soft-delete must cascade relationships (same as `delete_note`).
- MCP CORS may reflect Origin without credentials; Bearer auth is required for data.
- Public subscribe/unsubscribe/feedback require Turnstile.
- Dual DB backends (Postgres + D1) and pgvector storage without vector search are product choices — do not “simplify” without asking.

## Index

- [src/service/AGENTS.md](src/service/AGENTS.md)
- [src/auth/AGENTS.md](src/auth/AGENTS.md)
- [src/flit_mcp/AGENTS.md](src/flit_mcp/AGENTS.md)
- [tests/AGENTS.md](tests/AGENTS.md)
- [alembic/AGENTS.md](alembic/AGENTS.md)
- [scripts/AGENTS.md](scripts/AGENTS.md)
- [docs/AGENTS.md](docs/AGENTS.md)
