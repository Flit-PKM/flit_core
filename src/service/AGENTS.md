# AGENTS.md — src/service

Business logic for notes, sync, billing, OAuth, MCP tokens, purge, newsletters.

## File map

- `sync.py` — compare/push for notes/categories/relationships/chunks/note_categories (god module)
- `note.py` / `note_persistence.py` — note CRUD; persistence keeps notesearch in sync
- `billing.py` / `entitlement.py` — Dodo + access-code gating
- `oauth.py` / `mcp_oauth.py` — connected-app vs MCP token issuance
- `user_hard_delete.py` / `user_prune.py` / `purge.py` — destructive cleanup
- `newsletter_campaign.py` — admin mailing-list sends

## Invariants

- Soft-delete note → soft-delete relationships (API and sync).
- Integrity conflicts use `begin_nested()`, not full `session.rollback()`.
- Newsletter: do not mark SENT when every recipient delivery fails.
- `hard_delete_user` must clear MCP tables on SQLite/D1 (no CASCADE reliance).

## Prefer / avoid

- Prefer shared `utc.py` helpers over local `_utcnow` copies.
- Prefer `public_url.public_base_url` over importing it from `mcp_oauth`.
- Avoid new micro-files for one-liners; avoid a second entitlement wrapper layer.

## See also

- [../../AGENTS.md](../../AGENTS.md)
