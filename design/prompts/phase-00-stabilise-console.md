# Phase 0 — Stabilise the console: login, session, errors

> **HISTORICAL — DO NOT EXECUTE.** Superseded by
> [`f0-console-contract.md`](f0-console-contract.md). This prompt would recreate revision
> `0022` with the wrong table names. Retained only as the record of the former P0–P9 plan.

> Paste this whole file as the only prompt of a fresh session.

## Objective

Make authentication, session handling and error rendering structural instead of incidental, so
that no screen can half-load and no failure can present itself as "Something went wrong · Try
again". This is the phase that unblocks every other phase, because today the console cannot be
trusted to tell us whether the backend is right.

## Read first

- `design/02-identity-and-onboarding.md` — the three endpoints, the resolver, the failure taxonomy
- `design/09-frontend-and-api-contract.md` — the five rules, the error envelope, the four states
- `design/10-migration.md` — the "Frontend migration" table
- `agent-assurance/PROJECT_STATE.md` and `agent-assurance/AGENTS.md`

## Scope

**In:**

1. `GET /v1/auth/config` — the server decides which providers exist and which onboarding mode
   applies, keyed optionally by email domain. Returns no secrets.
2. `POST /v1/auth/session` — server-side authorization-code + PKCE exchange, identity
   resolution, onboarding, then session creation. A failure creates no session anywhere.
3. `GET /v1/session/bootstrap` — member, account, org units, roles, permissions, visibility
   scopes, navigation manifest, capability flags, environments, freshness, in one response.
4. Server-side sessions: `sessions` table, opaque `HttpOnly; Secure; SameSite=Lax` cookie,
   `POST /v1/auth/refresh`, `POST /v1/auth/logout`, session list and revoke on the profile page.
5. Error envelope on every error path: `reason`, `message`, `detail`, `next`, `request_id`.
   Implement every reason code in the taxonomy table in `design/02`.
6. Frontend: one bootstrap query, server-driven navigation, a single `<DataBoundary>` that
   renders loading / empty / error / data from a reason code, URL-driven filters and tabs.
7. Remove the project precondition: `SuiteProjectProvider` becomes a filter, never a wall.
8. Replace the `Bearer dev.<email>` bypass in `services/api/app/api/deps.py` with a
   `development` provider kind in `auth_providers`, refused unless
   `accounts.deployment_mode = 'development'`.

**Explicitly out of scope** (do not start these here): org units, DL import, the model gateway,
MCP changes, ClickHouse, new dashboards. Only the plumbing that makes the console honest.

## Database (one Alembic revision, `0022_session_and_auth_providers`)

```
accounts            — new; copy from organizations preserving ids; organizations becomes a view
auth_providers      — as specified in design/02; seed one row from current env for the pilot
sessions            — server-side sessions, token_hash unique, revoke reason
```

Do not touch `members`, `access_grants` or anything else in this phase. If the revision needs a
second table you did not expect, stop and say so rather than widening silently.

## Backend work

- A `providers` module with one verification path per `kind` (`oidc`, `development`). OIDC
  verification: discovery document cached, JWKS cached with rotation, `iss`/`aud`/`exp`/`nonce`
  checked, 60 s clock skew allowance, and *explicit* errors for each failure rather than one
  generic exception.
- `claim_map` resolution exactly as specified — arrays tried in order, subject never derived
  from email, email trusted only when the provider says verified.
- The resolver from `design/02`, idempotent, with `invite` as the default onboarding mode. JIT
  only when the provider says so and the domain is allow-listed.
- Bootstrap response assembled in one query set; cache it per session with explicit
  invalidation on grant or membership change.
- Every `HTTPException` replaced by a typed error carrying a reason code. Add a lint or test that
  fails if any route can return an error without one.

## Frontend work

- Delete `VITE_OIDC_*` reads. The login screen renders buttons from `/v1/auth/config`; with no
  providers it says so, naming the configuration that is missing, and does not offer a broken
  button.
- Callback route posts to `/v1/auth/session` and navigates only on 200.
- `useBootstrap()` is the single source of identity, permissions and navigation. No component
  fetches identity on its own.
- `<DataBoundary>` wraps every screen. It takes `{ query, empty, children }` and renders the
  four states; the error state renders `message` plus the `next` action as a button.
- Tabs and filters move to the URL. Fix the reported bug where clicking one tab highlights
  three: active state derives from `useMatch`/pathname, never from local state.
- Remove every remaining `X-Org-Id`, `getOrgId`, `aap.orgId` and `OrgGate` reference; keep
  `scripts/check-runtime-contract.mjs` failing the build if they come back.

## Invariants to add as named tests

| Name | Assertion |
|---|---|
| `inv_no_session_without_member` | A failed onboarding leaves no row in `sessions` and no cookie |
| `inv_dev_provider_requires_dev_mode` | The `development` provider returns 403 when `deployment_mode != 'development'` |
| `inv_every_error_has_reason` | Every error response from every route contains a reason code |
| `inv_bootstrap_is_single_request` | Loading the shell issues exactly one identity-related request |
| `inv_no_build_time_auth` | No `VITE_OIDC_*` reference exists in `services/web/src` |

## Test plan

1. Unit: claim-map resolution across Entra, Okta and Keycloak claim shapes; JWKS rotation;
   expired and future-dated tokens; missing `email_verified`.
2. Unit: resolver idempotency — same claims twice produces one member, one identity, one login
   record and no duplicate grant.
3. Integration: invite → first login claims it → second login of the same person reuses it;
   login with no invitation returns `not_provisioned` with a `next` action.
4. Integration: logout revokes the session server side; a revoked session's next request is 401
   `session_expired` and the client recovers without a visible error.
5. Playwright: for `member`, `dl_admin` and `security_admin` fixtures, visit every route in the
   manifest; assert zero console errors, zero unhandled rejections, and that every screen
   reaches `data` or a purposeful `empty`.
6. Playwright regression for the reported bug: force `/v1/members/me` to 403 and assert the
   screen shows a named reason and a working action, not a generic red box.

## Acceptance criteria (the gate)

- [ ] Login works end to end through the server; the browser never talks to the IdP token endpoint.
- [ ] A failed onboarding shows a specific reason and leaves no session; a reload returns to a clean login with the reason still visible.
- [ ] Every route in the navigation manifest renders for all three personas with zero console errors.
- [ ] No screen depends on a project existing.
- [ ] Every error surface shows a reason code and, where applicable, a next action.
- [ ] `npm run check:runtime` and the full API test suite pass.

## Deliverables

Migration `0022`; `auth` domain (router, service, providers, schemas); `sessions`
repository; bootstrap endpoint; typed error envelope; `<DataBoundary>`; rewritten login and
callback screens; deleted dev bearer bypass; the five invariant tests; updated
`PROJECT_STATE.md`.

## Do not

- Do not add a "temporary" bypass of any kind. The last one caused this phase.
- Do not seed demo data. Fixtures stay behind the `demo` profile.
- Do not begin the org-unit model; P1 owns it and doing it here will conflict.
- Do not silently reverse anything in the design decisions table; contradict it explicitly, with the ID, or follow it.
