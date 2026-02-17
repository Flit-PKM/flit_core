# Password Reset – Frontend Implementation

This document describes how to implement the password reset flow in the frontend.

## API Endpoints

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/api/password-reset/request` | No | Request a reset email. Body: `{ email: string }`, optionally `{ email: string, cf_turnstile_response: string }` when Turnstile is enabled (see below) |
| GET | `/api/password-reset/{token}/confirm` | No | Redirect endpoint (used by email link) |
| POST | `/api/password-reset/confirm` | No | Set new password. Body: `{ token: string, new_password: string }` |

## Flow Overview

1. **Request**: User enters email, submits form → `POST /api/password-reset/request`
2. **Email link**: User clicks link → `GET /api/password-reset/{token}/confirm` → API redirects to `{base}/reset-password?token={token}` or `?error=expired`
3. **Set password**: User enters new password, submits → `POST /api/password-reset/confirm`

## Pages to Implement

### 1. Request Reset Page (e.g. `/forgot-password` or `/reset-password/request`)

**Purpose**: Collect email and trigger the reset email.

**Form fields**:
- `email` (required, validated as email)

**On submit**:
```typescript
const response = await fetch(`${API_BASE}/api/password-reset/request`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ email }),
});

const data = await response.json();
if (data.sent) {
  // Show success: "If that email exists, we've sent a reset link."
} else {
  // Show error: data.detail (e.g. "Please wait before requesting another reset email")
}
```

**UX notes**:
- Always show a generic success message (“If an account exists for this email, we’ve sent a reset link”) regardless of `sent`, to avoid user enumeration.
- If `sent === false` and `detail` is present, show that message (e.g. cooldown or not configured).

### 2. Set New Password Page (e.g. `/reset-password`)

**Purpose**: Show form to set a new password when user arrives from the email link.

**URL params**:
- `token` – Present when user came from the reset link (valid token)
- `error=expired` – Present when the link was invalid or expired

**Behavior**:
- If `error=expired` in the query string: show an error like “This reset link has expired. Please request a new one.” and a link to the request page.
- If `token` is present: show a form with:
  - `new_password` (required, min 8 chars, with confirmation field recommended)
  - Submit button

**On submit**:
```typescript
const response = await fetch(`${API_BASE}/api/password-reset/confirm`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ token, new_password }),
});

const data = await response.json();
if (data.success) {
  // Redirect to login with success message: "Password updated. Please sign in."
} else {
  // Show error: data.detail (e.g. "Invalid or expired reset link. Please request a new one.")
}
```

**Example route (SvelteKit)**:
```
src/routes/forgot-password/+page.svelte     → Request form
src/routes/reset-password/+page.svelte      → Set new password (reads ?token= or ?error=)
```

**Example route (Next.js)**:
```
app/forgot-password/page.tsx
app/reset-password/page.tsx
```

## Response Schemas

### POST /api/password-reset/request
```json
{ "sent": true }
// or
{ "sent": false, "detail": "Please wait before requesting another reset email" }
```

### POST /api/password-reset/confirm
```json
{ "success": true }
// or
{ "success": false, "detail": "Invalid or expired reset link. Please request a new one." }
```

## Validation

- `new_password`: minimum 8 characters (enforced by API; validate on client too)
- `email`: valid email format

## Cloudflare Turnstile

When the backend has `TURNSTILE_SECRET` configured, `POST /api/password-reset/request` requires a valid Turnstile token. Use the same pattern as the subscription form:

1. Add the Cloudflare Turnstile script and widget to the forgot-password page (same site key as subscriptions).
2. Include `cf_turnstile_response` in the JSON body when submitting:

```typescript
body: JSON.stringify({
  email,
  cf_turnstile_response: turnstileWidgetResponse,  // from the widget's callback
}),
```

Without a valid token, the API returns 400 with `"Human verification failed. Please try again."` If `TURNSTILE_SECRET` is not set, the token is optional and the endpoint works as before.

## Security

- Do not reveal whether an email is registered – always use a generic success message.
- Redirect to login after a successful reset.
- Consider adding a “Resend” link on the set-password page that goes back to the request page.
