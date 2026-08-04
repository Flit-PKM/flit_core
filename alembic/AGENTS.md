# AGENTS.md — alembic

Schema migrations. Single head; run `uv run alembic upgrade head`.

## Invariants

- Do not edit applied revisions; add a new revision for schema changes.
- Keep model metadata and migrations aligned (especially soft-delete/version columns).

## See also

- [../AGENTS.md](../AGENTS.md)
