# AGENTS.md — src/flit_mcp

MCP JSON-RPC tools/resources and OAuth authorization-server HTML/HTTP.

## File map

- `tools/pkm.py` — tool implementations (god module)
- `oauth/` — authorize/consent/token, CIMD, DCR, HTML
- `auth/` — resolve MCP Bearer/API key; `require_mcp_write`
- `rate_limit.py` — process-local sliding window (`ponytail:`)
- Entitlement for MCP usage is enforced once in `router_setup._mcp_auth_validator` (JSON-RPC `-32003`)

## Invariants

- MCP tokens ≠ login JWTs (`MCP_TOKEN_TYPE` / resolve path).
- Browser OAuth POSTs must bind to the authorize session cookie.
- `logo_uri` in HTML must be https or same-origin path only.

## Prefer / avoid

- Prefer `get_note_or_404(..., user_id)` via `_get_owned_note` for ownership.
- Avoid a second request-state auth path beside the contextvar.

## See also

- [../../AGENTS.md](../../AGENTS.md)
- [../../docs/mcp-integration.md](../../docs/mcp-integration.md)
