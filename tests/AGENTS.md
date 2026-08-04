# AGENTS.md — tests

Async pytest against in-memory SQLite.

## Prefer / avoid

- Prefer one focused check for non-trivial logic (OAuth validate, sync cascade, hard_delete, newsletter failure).
- Avoid expanding smoke/config/OpenAPI tests unless the surface itself changed.
- Mock Turnstile on public POST/DELETE that require it.

## See also

- [../AGENTS.md](../AGENTS.md)
