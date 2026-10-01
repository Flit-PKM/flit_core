# Admin outbound webhooks

Superusers can configure multiple outbound webhook endpoints that receive Flit admin monitoring events (signups, subscription lifecycle, feedback, access-code activation, and unhandled errors).

## Configuration

All endpoints require a superuser JWT (`Authorization: Bearer …`).

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/admin/webhooks/event-types` | Catalog of event type strings |
| `GET` | `/api/admin/webhooks` | List endpoints (secrets masked) |
| `POST` | `/api/admin/webhooks` | Create endpoint (generates signing secret) |
| `GET` | `/api/admin/webhooks/{id}` | Read one endpoint |
| `PATCH` | `/api/admin/webhooks/{id}` | Update endpoint |
| `DELETE` | `/api/admin/webhooks/{id}` | Delete endpoint |
| `POST` | `/api/admin/webhooks/{id}/rotate-secret` | Replace signing secret |
| `POST` | `/api/admin/webhooks/{id}/test` | Fire a test event (awaits delivery) |

Create body example:

```json
{
  "name": "Ops monitor",
  "url": "https://hooks.example.com/flit",
  "events": ["user.signup", "subscription.active", "error.unhandled"],
  "enabled": true
}
```

Create and rotate responses include the plaintext `secret` once (`whsec_` + base64). Copy it into the receiver; later GET/PATCH/list only expose `secret_set` and `secret_last4`.

In production (`ENVIRONMENT=production`), URLs must use `https`.

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
- `webhook-id`: message id (same as payload `id`)
- `webhook-timestamp`: unix seconds
- `webhook-signature: v1,<base64>`

Signing follows [Standard Webhooks](https://github.com/standard-webhooks/standard-webhooks): HMAC-SHA256 over `{id}.{timestamp}.{raw_body}`. Secrets are generated as `whsec_` + base64(24 random bytes). The receiver must **base64-decode** the secret (after stripping `whsec_`) to get the HMAC key.

### Verifying the signature

```python
import base64
import hashlib
import hmac

def verify(secret: str, body: bytes, msg_id: str, timestamp: str, header: str) -> bool:
    raw = secret[6:] if secret.startswith("whsec_") else secret
    raw += "=" * ((4 - len(raw) % 4) % 4)
    key = base64.b64decode(raw)
    signed = f"{msg_id}.{timestamp}.{body.decode()}".encode()
    expected = "v1," + base64.b64encode(
        hmac.new(key, signed, hashlib.sha256).digest()
    ).decode()
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
