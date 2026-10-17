# Audit Logging (Milestone 11)

**Status:** Phase 4, Milestone 11. Behavior layer on top of `audit_logs` (Milestone 4,
schema-only).

## What Gets Audited

`backend/api/services/audit.py::record_event()` writes one row per security-relevant action,
called from four router modules:

| Category | Actions | Recorded in |
|---|---|---|
| Authentication | `auth.register`, `auth.login`, `auth.login_failed`, `auth.logout` | `auth.py` |
| API key lifecycle | `api_key.created`, `api_key.revoked` | `api_keys.py` |
| RBAC / configuration | `org.created`, `org.member_added`, `org.member_role_changed`, `org.member_removed`, `project.created`, `project.deleted` | `organizations.py` |
| Job execution | `job.train_submitted`, `job.benchmark_submitted`, `job.benchmark_compare_submitted` | `management.py` |

`auth.login_failed` fires for both a wrong password and an inactive account, distinguished by a
`reason` field in `metadata` (`invalid_credentials` / `account_inactive`) — it has no resolvable
`user_id` (the whole point is the credentials didn't identify a valid, active account), so
`email` goes in `metadata` instead. Job-submission events only fire when the caller resolved a
project-scoped API key (`ProjectContext`), the same opt-in boundary Milestones 8–10 established —
they record at submission time, not completion, since "who kicked off this run" is the audit-worthy
fact, distinct from Milestone 10's own per-request usage metering.

## Why `record_event()` Shares the Caller's Session (Two Real Bugs Found Building This)

Unlike `usage.py` (Milestone 10), `record_event(db, ...)` takes the caller's request-scoped
session rather than opening its own. This was not the obvious choice — an isolated transaction was
tried first and reverted after breaking on real data:

1. **A separate session can't see the row it's about to reference.** `org.created`'s audit row
   references `organization_id=org.id` moments after that organization was inserted in the *same*,
   still-uncommitted request transaction. A fresh `session_scope()` runs as an independent
   transaction under Postgres's default READ COMMITTED isolation, which cannot see another
   transaction's uncommitted insert — every creation event (`org.created`, `project.created`,
   `auth.register`) would fail its own foreign-key constraint. Sharing the request's session is
   what lets these events reference rows created earlier in the same request.

2. **The tradeoff this creates:** a caller that raises right after logging must commit first.
   `login()`'s two failure branches (`InvalidCredentialsError`, `AccountInactiveError`) log
   `auth.login_failed` and then raise an `HTTPException`. Since `get_db()`'s teardown
   (`session_scope()`) rolls back the whole transaction on any propagating exception — including
   an intentional 401/403 — the audit row would be silently erased along with it unless the
   session is committed *before* the raise. Both branches call `db.commit()` immediately after
   `record_event()` for exactly this reason.

3. **A pre-existing FK bug, found while placing the `project.deleted` event.** `delete_project()`
   hard-deletes the row (`ProjectRepository.delete()`, not a soft-delete flag). Logging
   `project.deleted` with `project_id=project_id` after that delete violates
   `audit_logs`'s own FK to `projects` — the id no longer exists. Fixed by omitting `project_id`
   from that one event and relying on `resource_id` (a plain string column, no FK) to record which
   project it was.

4. **A latent session-corruption bug in `infer()`, found while tracing session lifecycles for (1).**
   `infer()`'s pre-existing (Milestone 8) experiment-creation `except Exception: logger.exception(...)`
   never rolled back the shared request session on failure. A failed flush there would leave `db` —
   the same session `_record_usage_safe()` and `get_db()`'s own commit-on-teardown still needed —
   in a state that raises on any further use, turning a successful `/infer` call into a 500 at
   response-commit time. Fixed by adding `db.rollback()` to that except block (and to
   `_record_usage_safe()`'s own, for the same reason).

Every `record_event()` call site still wraps its own write in a try/except that rolls back and
logs rather than raising — audit logging must never turn a successful request into a failure, the
same guarantee Milestones 8–10 give experiment/registry/usage recording.

## Endpoint

Admin+ only — a log of who did what, including other members' logins and permission changes, is
more sensitive than the Viewer-readable resources (experiments, usage) Milestones 8/10 exposed to
any project member.

| Method | Path | Auth |
|---|---|---|
| GET | `/orgs/{organization_id}/audit-logs?action=&resource_type=&user_id=&limit=100` | Admin+ of `organization_id` |

Authentication events (`auth.*`) have `organization_id=None` (a login isn't scoped to any one
organization) and so never appear through this endpoint — they're only visible via a direct table
query. This is a known, deliberate scope limit: there is no cross-org "my own login history"
endpoint in Phase 4.

## Testing

`tests/test_audit.py` — integration tests against the real dev Postgres container:
register/login/logout recorded and queryable by `user_id`, a failed login recorded with no
`user_id` and the right `reason`, API key create/revoke (checked directly since API keys aren't
org-scoped), the full org/project/member lifecycle surfaced through the endpoint, a
project-scoped training job's submission event, RBAC enforcement (403 for Viewer, 200 for Admin),
and filtering by `action`.
