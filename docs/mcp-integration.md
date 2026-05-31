# Flit MCP Integration Guide

This guide describes how AI agents and external clients connect to Flit Core's MCP server for personal knowledge management (PKM).

## Overview

When `MCP_ENABLED=true`, Flit exposes a JSON-RPC 2.0 MCP server at `POST /mcp` with tools for notes, categories, and relationships. Authentication uses OAuth (recommended) or API keys (`flit_mcp_…`).

## Discovery

| Endpoint | Purpose |
|----------|---------|
| `GET /mcp/catalog` | Machine-readable list of tools and `flit://` resources with `inputSchema` |
| `GET /openapi.json` | Full OpenAPI spec; includes `x-mcp-tools` when `MCP_OPENAPI_INCLUDE=true` |
| `POST /mcp` | JSON-RPC: `tools/list`, `tools/call`, `resources/list`, `resources/read` |

Required header for MCP requests:

```
MCP-Protocol-Version: 2025-06-18
Authorization: Bearer <token>
```

## Authentication

### OAuth (recommended for desktop agents)

1. Client receives `401` on unauthenticated `POST /mcp` with `WWW-Authenticate` pointing to `/.well-known/oauth-protected-resource`.
2. User authorizes via `GET /mcp/oauth/authorize` (PKCE, `resource={PUBLIC_BASE_URL}/mcp`).
3. Client exchanges code at `POST /mcp/oauth/token`.
4. Scopes: `read` (read-only tools) or `read write` (full PKM access).

### API keys

Create keys with a main-app JWT at `POST /mcp/api-keys`. Pass the key as `Authorization: Bearer flit_mcp_…`.

## Scopes and write tools

Read-only tokens hide write tools from `tools/list` and block `tools/call` on mutations. Write tools include `create_note`, `update_note`, `append_to_note`, `delete_note`, category/relationship CRUD, and note–category linking.

## Token-efficient content controls

Large notes can consume context quickly. Use these parameters on read tools:

| Parameter | Values | Effect |
|-----------|--------|--------|
| `return_mode` | `full` (default), `metadata`, `snippet` | `metadata` omits `content` and adds `snippet`; `snippet` returns a short excerpt |
| `max_content_chars` | integer | Truncates content with `…` in `full` or `snippet` mode |
| `return_format` (query_graph) | `flat` (default), `tree` | `flat` returns deduplicated `nodes` + `edges`; `tree` returns nested `root` with `children` |

**Recommendations:**

- **`list_notes`**: use `return_mode=metadata` or `snippet` for discovery; default snippet length is 500 characters.
- **`get_note`**: use `return_mode=full` when you need the complete body.
- **`query_graph`**: defaults to `return_mode=snippet` and `return_format=flat`. Use `return_format=tree` when relational depth and branching paths matter; use `flat` for token-efficient post-processing.

All shaped responses include `content_length` when content metadata is available.

## Example agent workflows

### Research a topic in your notes

```
1. list_notes(search="project alpha", return_mode="metadata", limit=20)
2. get_note(note_id=<promising id>, return_mode="full")
3. query_graph(starting_id=<id>, max_depth=2, relation_type="REFERENCES")
4. get_notes(note_ids=[...], include_categories=true, return_mode="snippet")
```

### Capture incremental notes

```
1. create_note(title="Meeting log", content="## 2026-05-31\nInitial context")
2. append_to_note(note_id=<id>, content="Decision: ship Phase 1 MCP improvements.")
```

### Organize and connect

```
1. list_categories()
2. link_note_to_category(note_id=<id>, category_id=<id>)
3. create_relationship(note_a_id=<a>, note_b_id=<b>, type="RELATED_TO")
```

## Tool reference (read tools)

| Tool | Purpose |
|------|---------|
| `list_notes` | Discovery with search, category filter, date range, `pinned_only`, sorting |
| `get_note` | Single note with categories and relationships |
| `get_notes` | Batch retrieval (max 50 ids); returns `found` and `missing_ids` |
| `query_graph` | BFS traversal (depth 1–3, max 50 nodes); `return_format=flat` (nodes + edges) or `tree` (nested root) |
| `list_relationships` | 1-hop adjacency for one note |
| `list_categories` / `get_category` | Category discovery |
| `list_note_categories` | Categories linked to a note |
| `get_user_profile` | User info and entitlement status |

## Tool reference (write tools)

| Tool | Purpose |
|------|---------|
| `create_note` | Create a BASE note |
| `update_note` | Partial update (replaces `content` when provided) |
| `append_to_note` | Append text without full replacement |
| `delete_note` | Soft-delete |
| `create_category` / `update_category` / `delete_category` | Category CRUD |
| `create_relationship` / `delete_relationship` | Link or unlink notes |
| `link_note_to_category` / `unlink_note_from_category` | Category assignment |

## Error handling

Not-found errors include actionable hints, for example:

```
Note 42 not found or access denied. Verify the ID via list_notes.
```

When billing is configured, MCP calls require an active subscription or access-code grant.

## Rate limiting

Per-user rate limits apply when `MCP_RATE_LIMIT_ENABLED=true` (default `120/minute`). Reduce call volume by using `get_notes` batch retrieval and content controls.

## Resources

| URI | Content |
|-----|---------|
| `flit://user/profile` | User profile JSON |
| `flit://note/{note_id}` | Single note (`NoteRead`, no embedded graph) |
| `flit://category/{category_id}` | Category JSON |

## Local development

```bash
# Enable MCP in .env
MCP_ENABLED=true
PUBLIC_BASE_URL=http://127.0.0.1:8000

# List tools via catalog
curl -s http://127.0.0.1:8000/mcp/catalog | jq '.tools[].name'

# Call list_notes (replace TOKEN)
curl -s -X POST http://127.0.0.1:8000/mcp \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -H "MCP-Protocol-Version: 2025-06-18" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"list_notes","arguments":{"return_mode":"metadata","limit":5}}}'
```

See [README.md](../README.md) for OAuth setup, CORS, and entitlement details.
