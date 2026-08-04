# AGENTS.md — scripts

CLI wrappers around services (purge, repair relationships, grant superuser).

## Prefer / avoid

- Prefer calling `service.*` rather than reimplementing deletes/authz.
- `grant_superuser.py` may talk to DB with `DATABASE_URL` only — keep it thin.

## See also

- [../AGENTS.md](../AGENTS.md)
