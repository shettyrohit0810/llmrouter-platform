# Authentication

**Status:** Phase 4, Milestone 2. Implements the authentication model designed in
`docs/design.md`. No route outside `/api/v1/auth/*` and `/api/v1/api-keys/*`
requires authentication yet — enforcing it on the existing management/OpenAI-compatible surface is
Milestone 3's RBAC middleware, not this milestone (see that doc's Migration Strategy §2).

## Two Client Types, One Dependency Surface

- **Human users** (dashboard, interactive API use): email+password or OAuth (Google/GitHub),
  authenticated via a JWT **access token** in `Authorization: Bearer <token>`.
- **Programmatic clients**: an **API key** in the `X-API-Key` header.

`backend/api/auth/dependencies.py` exposes both: `get_current_user` (JWT only — used by
account-management endpoints where "prove you're a logged-in human" is the point, e.g. API key
creation) and `get_current_principal` (JWT **or** API key — built now, not yet wired into any
route; Milestone 3's RBAC middleware is its first consumer).

## Tokens

| Token | Format | Storage | Lifetime | Revocable? |
|---|---|---|---|---|
| Access | JWT (HS256) | Not stored — verified by signature only | 15 min (`ACCESS_TOKEN_TTL_MINUTES`) | No — short TTL is the mitigation |
| Refresh | Opaque random string | sha256 hash in `refresh_tokens` | 30 days (`REFRESH_TOKEN_TTL_DAYS`) | Yes — DB lookup, `revoked` flag |
| API key | Opaque random string, `lr_live_` prefix | sha256 hash in `api_keys` | None by default (`expires_at` nullable) | Yes — DB lookup, `revoked` flag |
| Password reset / email verification | JWT with a `purpose` claim | Not stored (stateless) | 1h / 24h | Self-limiting (see below) |

Access tokens are deliberately never checked against the database — verifying only the signature
means authenticating a request costs zero DB round trips, at the cost of not being able to revoke
one before it expires (mitigated by the 15-minute TTL). Refresh tokens and API keys are the
opposite trade: a DB lookup on every use, in exchange for real-time revocability.

**Refresh rotation:** every `POST /api/v1/auth/refresh` revokes the presented token and issues a
brand new pair — a refresh token can be used exactly once. This means a leaked-but-unused refresh
token stops working the moment the legitimate client refreshes, rather than remaining valid for
its full 30-day window. Verified in `tests/test_auth.py::
test_refresh_rotates_and_revokes_old_token`.

**Password reset / email verification are single-use without a "used tokens" table:**
password-reset tokens embed a fingerprint (`hash_token(user.hashed_password)[:16]`) of the
password hash at issuance time; confirming a reset changes the hash, so replaying the same token
fails the fingerprint check on its second use (verified in `tests/test_auth.py::
test_password_reset_confirm_changes_password_and_is_single_use`). Email verification tokens don't
need this trick — confirming twice is harmlessly idempotent (`is_email_verified` just stays
`True`).

## Password Hashing

`bcrypt` directly (`backend/api/auth/security.py`), not `passlib` — passlib's bcrypt backend has a
known compatibility gap with `bcrypt>=4.1` (its version-detection code expects an attribute recent
bcrypt releases removed). Passwords over bcrypt's 72-byte input limit are rejected explicitly at
hashing time (`ValueError`) rather than silently truncated.

## OAuth (Google, GitHub)

Standard authorization-code flow, implemented directly against each provider's token/userinfo
endpoints via `httpx` (`backend/api/auth/oauth.py`) rather than a full OAuth client library —
`GoogleOAuthProvider` and `GithubOAuthProvider` both satisfy the same `OAuthProvider` protocol, so
`backend/api/routers/auth.py`'s callback handler has one code path for both providers, not one per
provider.

- `GET /api/v1/auth/oauth/{provider}/login` returns `{"authorization_url": "..."}` (JSON, not a
  redirect — the dashboard, as a separate SPA client, performs the redirect itself; see "REST API
  must remain the only public interface").
- `GET /api/v1/auth/oauth/{provider}/callback?code=...` exchanges the code, links to an existing
  `OAuthAccount` if one exists, otherwise finds-or-creates a `User` by email (marking
  `is_email_verified=True` — the provider already verified it) and creates the link, then issues
  the same access/refresh token pair as password login.
- **Neither provider is configured in this environment** (no client ID/secret) — both return `501`
  from `/login`, verified in `tests/test_auth.py::
  test_oauth_login_returns_501_when_not_configured`. This is the same "feature absent without
  config" pattern Phase 3 used for LLM provider API keys, not a bug.
- **Known tech debt:** the `state` parameter is generated but not persisted/verified server-side —
  proper CSRF protection for the OAuth flow needs a short-lived server-side state store, which
  needs Redis (Milestone 5, not yet available at this point in the phase). Flagged explicitly in
  the completion report's tech-debt section, not silently shipped as if it were complete.

## Email Verification (Stub)

`EmailSender` protocol + `ConsoleEmailSender` (`backend/api/auth/email.py`) — logs the email
instead of sending it, per the approved spec ("Email verification interfaces (stub only)"). A real
provider (SES, Postmark, ...) implements the same protocol later; no call site
(`service.request_password_reset`, `service.request_email_verification`) changes.

## Endpoints

| Method | Path | Auth required | Notes |
|---|---|---|---|
| POST | `/api/v1/auth/register` | none | 409 if email taken; fires (stubbed) verification email |
| POST | `/api/v1/auth/login` | none | 401 wrong credentials, 403 inactive account |
| POST | `/api/v1/auth/refresh` | none (refresh token in body) | rotates |
| POST | `/api/v1/auth/logout` | none (refresh token in body) | revokes that token only |
| GET | `/api/v1/auth/me` | JWT | |
| POST | `/api/v1/auth/password-reset/request` | none | always 202, no enumeration |
| POST | `/api/v1/auth/password-reset/confirm` | none (token in body) | 400 invalid/expired/reused |
| POST | `/api/v1/auth/email/verify` | none (token in body) | idempotent |
| POST | `/api/v1/auth/email/resend` | JWT | |
| GET | `/api/v1/auth/oauth/{provider}/login` | none | 404 unknown provider, 501 unconfigured |
| GET | `/api/v1/auth/oauth/{provider}/callback` | none (code in query) | |
| POST | `/api/v1/api-keys` | JWT | full key returned once, never again |
| GET | `/api/v1/api-keys` | JWT | never includes the full key |
| DELETE | `/api/v1/api-keys/{id}` | JWT | idempotent; 404 only for a nonexistent/other-user key |

## Database

Migration `d6fe79af4b79` adds `users`, `oauth_accounts`, `refresh_tokens`, `api_keys` — see that
migration's own docstring for rollback notes, and
`docs/design.md`'s Database Schema section for the full ERD and the ordering
rationale (identity tables now; organization/project/RBAC tables in Milestone 3; the remaining
domain tables in Milestone 4). `api_keys.created_by` references `users.id` directly — there is no
`project_id` yet, added by a Milestone 3 migration once `projects` exists.

## Configuration

New `BackendConfig` fields, all overridable via env var: `JWT_SECRET_KEY` (⚠️ defaults to an
insecure dev-only value — **must** be overridden in any shared environment; no runtime check
enforces this, it's a documented operational responsibility), `JWT_ALGORITHM` (default `HS256`),
`ACCESS_TOKEN_TTL_MINUTES` (15), `REFRESH_TOKEN_TTL_DAYS` (30),
`GOOGLE_OAUTH_CLIENT_ID`/`_SECRET`/`_REDIRECT_URI`, `GITHUB_OAUTH_CLIENT_ID`/`_SECRET`/`_REDIRECT_URI`.

## Testing

- `tests/test_security.py` — unit tests for hashing/JWT primitives, no database.
- `tests/test_auth.py` — integration tests against the real dev Postgres container
  (same convention as `tests/test_health_db.py`), covering the full
  register/login/refresh/logout/reset/verify/API-key lifecycle plus negative cases (wrong
  password, reused refresh token, reused reset token, cross-user API key revoke, unconfigured/
  unknown OAuth provider). Each test uses a UUID-based email so tests are independent and safely
  rerunnable against the same database without a per-test transaction-rollback fixture.
