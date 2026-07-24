# Admin outbound webhooks

Superusers can configure multiple outbound webhook endpoints that receive Flit admin monitoring events (signups, subscription lifecycle, feedback, access-code activation, and unhandled errors).

## Configuration

All endpoints require a superuser JWT (`Authorization: Bearer …`).

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/admin/webhooks/event-types` | Catalog of event type strings |
| `GET` | `/api/admin/webhooks` | List endpoints (secrets masked) |
| `POST` | `/api/admin/webhooks` | Create endpoint |
| `GET` | `/api/admin/webhooks/{id}` | Read one endpoint |
| `PATCH` | `/api/admin/webhooks/{id}` | Update endpoint |
| `DELETE` | `/api/admin/webhooks/{id}` | Delete endpoint |
| `POST` | `/api/admin/webhooks/{id}/test` | Fire a test event (awaits delivery) |

Create body example:

```json
{
  "name": "Ops monitor",
  "url": "https://hooks.example.com/flit",
  "events": ["user.signup", "subscription.active", "error.unhandled"],
  "secret": "optional-hmac-secret",
  "enabled": true
}
```

In production (`ENVIRONMENT=production`), URLs must use `https`.

Secrets are never returned in full: responses expose `secret_set` and `secret_last4` only. Use `clear_secret: true` on PATCH to remove a secret.

## Event catalog

| Type | When |
|------|------|
| `user.signup` | New user created (email, Google, MCP OAuth) |
| `subscription.active` | Subscription becomes active |
| `subscription.renewed` | Subscription renewed |
| `subscription.on_hold` | Subscription on hold |
| `subscription.failed` | Subscription payment failed |
| `subscription.cancelled` | Subscription cancelled |
| `subscription.expired` | Subscription expired |
| `subscription.plan_changed` | Plan changed |
| `feedback.created` | New product feedback |
| `access_code.activated` | Access code redeemed |
| `error.unhandled` | Unexpected / 5xx failures |
| `webhook.test` | Manual test fire only |

## Payload

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "type": "user.signup",
  "created_at": "2026-07-24T04:00:00+00:00",
  "data": {
    "user_id": 42,
    "email": "user@example.com",
    "username": "user"
  }
}
```

Headers:

- `Content-Type: application/json`
- `X-Flit-Event: <event type>`
- `X-Flit-Signature: sha256=<hex>` (only when a secret is configured)

### Verifying the signature

```python
import hashlib
import hmac

def verify(secret: str, body: bytes, header: str) -> bool:
    expected = "sha256=" + hmac.new(
        secret.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, header)
```

## Delivery semantics

Production events are **fire-and-forget** after a successful DB commit. Failures are logged; they never fail the user-facing request. There is no automatic retry queue.

## Test events

`POST /api/admin/webhooks/{id}/test` with optional body:

```json
{ "event_type": "user.signup" }
```

- Omit `event_type` (or use `webhook.test`) for a simple ping payload.
- Any other catalog type sends a fixed sample `data` shape for that event.
- Delivery is **awaited**; the response includes `ok`, `status_code`, `latency_ms`, and `error`.
- Targets that endpoint only and ignores its `enabled` flag and event filters (so you can verify a disabled endpoint during setup).
