# Dodo Payments billing

Flit Core uses [Dodo Payments](https://docs.dodopayments.com/) for subscription checkout, webhooks, and customer self-service.

## Environment variables

Set all of these together for production billing. Partial config disables entitlement gating and checkout.

| Variable | Required | Description |
|----------|----------|-------------|
| `DODO_PAYMENTS_API_KEY` | Yes | API key from Dodo dashboard (test or live) |
| `DODO_PAYMENTS_WEBHOOK_SECRET` | Yes | Webhook signing secret from **Developer → Webhooks** |
| `DODO_PAYMENTS_ENVIRONMENT` | No | `test` (default) or `live` |
| `DODO_PAYMENTS_MONTHLY` | Yes* | Dodo product ID for the monthly plan |
| `DODO_PAYMENTS_ANNUAL` | Yes* | Dodo product ID for the annual plan |
| `DODO_PAYMENTS_SUBSCRIPTION_PRODUCT_ID` | No | Legacy fallback for `is_billing_configured` when plan IDs are unset |
| `PUBLIC_BASE_URL` | Yes (prod) | Used to build the webhook URL below |

\*At least one of `DODO_PAYMENTS_MONTHLY` or `DODO_PAYMENTS_ANNUAL` is required for checkout and entitlement gating.

## API endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/billing/plans` | No | Plan details from Dodo (cached 5 min) |
| POST | `/api/billing/checkout` | JWT | Create checkout session; returns `checkout_url` |
| POST | `/api/billing/complete` | JWT | Verify subscription after redirect; upserts local record |
| GET | `/api/billing/subscription` | JWT | Current user's subscription status |
| GET | `/api/billing/portal` | JWT | Customer portal URL (cancel, update payment method) |
| POST | `/api/billing/webhooks/dodo` | Dodo signature | Webhook receiver |

## Checkout flow

1. Frontend calls `GET /api/billing/plans` and `POST /api/billing/checkout` with `product_id` and optional `return_url`.
2. User completes payment on Dodo's hosted checkout.
3. Dodo redirects to `return_url` with `subscription_id` and `status` query params.
4. Frontend calls `POST /api/billing/complete` with those values.
5. Backend verifies the subscription with Dodo and stores it in `plan_subscriptions`.

Checkout sessions include `metadata.user_id` and prefill the authenticated user's email and name.

## Webhook setup

In the Dodo dashboard (**Developer → Webhooks**):

1. Add endpoint: `POST {PUBLIC_BASE_URL}/api/billing/webhooks/dodo`
2. Copy the signing secret into `DODO_PAYMENTS_WEBHOOK_SECRET`.
3. Subscribe to these events (minimum):

- `subscription.active`
- `subscription.updated`
- `subscription.on_hold`
- `subscription.cancelled`
- `subscription.expired`
- `subscription.renewed`
- `subscription.plan_changed`

Webhooks use the [Standard Webhooks](https://standardwebhooks.com/) spec. The backend verifies signatures via the official Python SDK and deduplicates by the `webhook-id` header.

## Entitlement

When billing is configured (`DODO_PAYMENTS_API_KEY` plus at least one plan product ID), sync (`/api/sync/*`) and MCP usage require `plan_subscriptions.status == active` or a non-expired access-code grant.

Subscription states from Dodo: `active`, `on_hold`, `cancelled`, `expired`, `pending`. Only `active` grants access.

## Customer portal

`GET /api/billing/portal` returns a short-lived Dodo portal URL so users can cancel, update payment methods, or recover from `on_hold` without admin intervention.
