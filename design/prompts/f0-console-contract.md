# F0 — Console contract: login, session, errors

> Paste this whole file as the only prompt of a fresh session.

## Objective

Make authentication, session handling and error rendering structural, so no screen can
half-load and no failure can present itself as "Something went wrong · Try again". This
unblocks every later slice, because today the console cannot be trusted to tell us whether
the backend is right.

This is **not** a rewrite of identity. Members, Entra OIDC, Platform Keys and account owner
roles already exist (`0017`–`0021`). Close the contract holes; do not invent a parallel
login stack.

## Read first

- `design/prompts/README.md` — sequence and rules
- `design/02-identity-and-onboarding.md` — endpoints, resolver, failure taxonomy
- `design/09-frontend-and-api-contract.md` — five rules, error envelope, four states
- `design/10-migration.md` — frontend migration table
- `agent-assurance/AGENTS.md` and `PROJECT_STATE.md`
- Current code: `services/web/src/features/auth/`, `services/api/app/api/deps.py`,
  `services/web/src/App.tsx`
- Existing revision `0022_auth_sessions_and_providers.py` and
  `app/db/models/auth.py`

## Scope

**In:**

1. `GET /v1/auth/config` — server decides which providers exist. Returns no secrets. Delete
   `VITE_OIDC_*` reads from the login screen.
2. Server-side session if not already durable: opaque `HttpOnly; Secure; SameSite=Lax`
   cookie, refresh, logout, session list + revoke on `/profile`. A failed onboarding creates
   **no** session row and **no** cookie.
3. `GET /v1/session/bootstrap` — member, account, roles, permissions, visibility scopes,
   **navigation manifest**, capability flags, freshness. One request. The shell renders from
   it.
4. Error envelope on every error path: `reason`, `message`, `detail`, `next`, `request_id`.
   Implement every reason code in `design/02`. Add a test that fails if any route can return
   an error without a reason.
5. `<DataBoundary>` that renders loading / empty / error / data from a reason code. Wrap
   the screens you touch; do not migrate every legacy screen in this session.
6. `SuiteProjectProvider` becomes a **filter**, never a wall. Observe must render with no
   project selected.
7. Replace `Bearer dev.<email>` in `deps.py` with a `development` provider kind, refused
   unless deployment mode is development. Keep the `localhost` email domain — never a
   customer or employer domain.

**Out:** org-unit tree, ledger tables, gateways, DLP, ClickHouse, new product screens,
accreditation work. F1 owns **ledger** schema. F2 owns nav/IA.

## Database

Revision `0022_auth_sessions_and_providers` already defines `auth_providers` and
`auth_sessions`. Inspect whether it is applied, export its ORM models, and implement against
it. **Do not create another auth migration unless inspection proves a required field is
missing.** If a follow-up is needed, it must come after the real current head and contain
only the missing field.

Name the human browser table `auth_sessions` — **not** `sessions`. Agent context windows
will be `agent_sessions` in F1; colliding those two names is a defect.

Do not copy `organizations` → `accounts` here. F1 decides that rename.

## Invariants

| Name | Assertion |
|---|---|
| `inv_no_session_without_member` | Failed onboarding leaves no `auth_sessions` row and no cookie |
| `inv_dev_provider_requires_dev_mode` | Development provider is 403 unless development mode |
| `inv_every_error_has_reason` | Every error response contains a reason code |
| `inv_bootstrap_is_single_request` | Loading the shell issues exactly one identity-related request |
| `inv_no_build_time_auth` | No `VITE_OIDC_*` in `services/web/src` |

## Test plan

1. Claim-map unit tests (Entra / Okta / Keycloak shapes; JWKS rotation; expired tokens).
2. Resolver idempotency: same claims twice → one member, one identity, one login record.
3. Invite → first login claims it; unknown person → `not_provisioned` with a `next` action.
4. Logout revokes server-side; next request is 401 `session_expired`; client recovers.
5. Playwright: `member`, `security_admin` visit every **currently licensed** route; zero
   console errors; every screen reaches `data` or a purposeful `empty`.
6. Force a 403 on a me-endpoint; the screen shows a named reason and a working action, not
   the generic `ErrorState` title "Something went wrong".
7. Fresh and existing PostgreSQL: confirm `0022` model/migration drift is zero and RLS
   applies to both auth tables.

## Gate

- [ ] Browser never talks to the IdP token endpoint.
- [ ] Failed onboarding shows a specific reason and leaves no session.
- [ ] No screen depends on a project existing.
- [ ] `0022` is recorded honestly as written or applied; no duplicate auth table exists.
- [ ] `npm run check:runtime` and the API test suite pass.
- [ ] `PROJECT_STATE.md` updated.

## Do not

- Do not add a temporary bypass. The last one caused this work.
- Do not seed demo data.
- Do not start the org-unit model or the action ledger.
- Do not silently reverse a recorded decision; contradict it with the ID or follow it.
