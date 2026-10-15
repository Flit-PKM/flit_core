# AGENTS.md — src/auth

Login JWT, password hashing, FastAPI dependencies, typed one-shot tokens (verify / password-reset).

## File map

- `dependencies.py` — `get_current_user`, sync OAuth context, superuser
- `jwt.py` — login access tokens (`sub` = email)
- `password.py` — passlib pbkdf2
- `verify_token.py` / `password_reset_token.py` — short-lived typed JWTs
- `google_id_token.py` — Google Sign-In for main app

## Invariants

- Login path uses email in `sub`; never treat OAuth/MCP tokens as login JWTs.
- Password login (`/auth/login`, `/auth/login-json`) returns one 401 `Incorrect email or password` for unknown email, wrong password, OAuth-only, and inactive. Do not auto-create on login.
- `POST /auth/register` returns a login `Token`. Duplicate email is 409. Unverified users may still log in.
- Revocation checks `jti` against `revoked_jwts`.
- Sliding renewal is `POST /auth/refresh` (still-valid login JWT only). Do not mix with `/oauth` refresh.

## Prefer / avoid

- Prefer `decode_login_token_claims` over inventing another verify helper.
- Avoid duplicate OAuth deps; sync uses `get_sync_oauth_context` only.

## See also

- [../../AGENTS.md](../../AGENTS.md)
