# Admin email templates

User-facing transactional mail is a fixed catalog. Superusers can override copy and disable individual keys. Newsletters stay a separate mailing-list broadcast.

## Keys

| Key | Default enabled | Trigger |
|-----|-----------------|---------|
| `welcome` | yes | `create_user` (password, Google, MCP, admin-created) |
| `email_verify` | yes | Password `POST /api/auth/register`, and `GET /api/verify` resend |
| `password_reset` | yes | `POST /api/password-reset/request` (unknown/unverified addresses still look successful) |
| `mailing_list_confirm` | yes | New public mailing-list subscribe only |
| `subscription.active` / `.renewed` / `.on_hold` / `.failed` / `.cancelled` / `.expired` / `.plan_changed` | **no** | Dodo webhook `_handle_subscription_event` only — not checkout completion |

`enabled=false` skips that send, including verify/reset. Turn templates back on before relying on those flows.

## Placeholders

Replace `{name}` only. Unknown `{foo}` is left as-is.

| Placeholder | Used by |
|-------------|---------|
| `{username}` | welcome, verify, reset, billing |
| `{email}` | all |
| `{link}` | verify, reset (existing confirm URL) |
| `{expire_hours}` | verify, reset |
| `{status}` | billing |
| `{product_id}` | billing |

## Admin API

All routes require a superuser JWT. Prefix: `/api/admin/email-templates`.

| Method | Path | Effect |
|--------|------|--------|
| GET | `/` | All catalog keys, resolved copy, placeholders, `is_overridden`, `enabled` |
| GET | `/{key}` | One template; 404 if not in catalog |
| PATCH | `/{key}` | Upsert `subject`, `body_text`, `body_html`, `enabled` |
| POST | `/{key}/reset` | Delete override; next send uses the code default |
| POST | `/{key}/test` | Send to the current superuser with sample placeholder values |

There is no POST to invent keys.

Transport is Postmark SMTP (`POSTMARK_SMTP_TOKEN`). Failed or unconfigured send never fails the user request.
