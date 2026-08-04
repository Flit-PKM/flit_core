# AGENTS.md — alembic

Schema migrations. Single head; run `uv run alembic upgrade head`.

## Clean-break history (2026)

History was squashed to:
1. `baseline_001` — create current Postgres schema (no chunks)
2. `drop_chunks_002` — `DROP TABLE IF EXISTS chunks` for DBs stamped from the old chain

**Existing DB already at old head** (version table still says e.g. `add_admin_webhooks`):  
`uv run alembic stamp --purge baseline_001 && uv run alembic upgrade head`  

`--purge` clears the orphaned old revision id (files are gone after the squash). Do **not** run baseline `upgrade()` on a DB that already has tables.

**Empty DB:** `uv run alembic upgrade head`

## Invariants

- Do not edit applied revisions; add a new revision for schema changes.
- Keep model metadata and migrations aligned.

## See also

- [../AGENTS.md](../AGENTS.md)
