# 09 · Frontend and API contract

Sketch: `diagrams/10-dashboards-and-access.excalidraw`

The console is currently the least trustworthy part of the system: screens half-load, a 403
from one of several parallel queries paints a generic error, and a reload produces a different
failure from the first attempt. That is an architecture problem, not a styling problem.

## Five rules

1. **One bootstrap.** `GET /v1/session/bootstrap` returns member, account, org units, roles,
   permissions, visibility scopes, navigation manifest, capability flags, environments and
   data freshness. The shell renders from that single response. There is no moment when
   navigation exists but permissions do not.
2. **Server-driven navigation.** A module the caller cannot use is absent from the manifest,
   not present-and-broken. A deep link into a hidden module renders a purposeful "request
   access" page naming who can approve.
3. **Every response carries a reason code.** No screen ever renders a bare error string. If a
   response has no reason code, the error boundary says *that* — with the request id — because
   it is an API bug and should be reported as one.
4. **Four states per screen, always.** `loading` (skeleton shaped like the result, not a
   spinner in a box) · `empty` (what this is for and the single action that fills it) ·
   `error` (reason code, human sentence, working retry) · `data` (with stated freshness).
   A screen without all four is not done, and the UI test asserts each one.
5. **No screen requires a project.** Project is a filter, never a precondition. The current
   "no runtime projects" wall is the kind of dead end that makes a product feel broken on
   first login.

## Endpoint families

| Family | Shape | Notes |
|---|---|---|
| `/v1/auth/*` | config, session, refresh, logout | The only unauthenticated family |
| `/v1/session/bootstrap` | one object | Cached per session, invalidated by grant/org change |
| `/v1/directory/*` | members, org units, groups, invitations, sync status | Cursor-paginated |
| `/v1/access/*` | roles, grants, requests, approvals | Every mutation needs a reason string |
| `/v1/registry/*` | providers, endpoints, candidates, aliases, agents | `registry:read` filtered by grant |
| `/v1/mcp/*` | servers, snapshots, capabilities, grants, quarantine, preflight | List is grant-filtered |
| `/v1/policy/*` | policies, bindings, simulate, activate, bundles | Simulate before activate is enforced server side |
| `/v1/insights/*` | usage, cost, denials, adoption, graph | Aggregates only; `scope` intersected server side |
| `/v1/activity/*` | events, event detail, payload reveal request | Narrow windows only; each read audited |
| `/v1/audit/*` | events, export, verify chain | Append-only |
| `/v1/keys/*` | platform keys, rotate, revoke, client config | Secret shown once, never again |

Conventions: cursor pagination (`cursor`, `limit`, `has_more`) — never offset, because these
tables move while you page; `If-Match` on every update; idempotency keys on every create;
`X-Request-Id` echoed everywhere and shown in every error surface; `freshness_at` on every
aggregate; `withheld_fields[]` whenever authorization removed something from a response.

## Error envelope

```json
{
  "reason": "scope_outside_grant",
  "message": "That organisation unit is outside your visibility.",
  "detail": { "requested": "/northwind/eng", "visible": ["/northwind/eng/ide-users"] },
  "next": { "kind": "request_access", "role": "unit_manager", "approvers": ["priya@…"] },
  "request_id": "01JB…",
  "docs": "/docs/errors/scope_outside_grant"
}
```

`next` is what makes the console usable: the UI renders it as a button. Every reason code in
[02-identity-and-onboarding.md](02-identity-and-onboarding.md) has a `next`, or it is not
finished.

## Frontend architecture

- **React Router** with a route per module and a nested layout per suite, one URL per view —
  tabs that do not change the URL are the bug reported earlier ("clicking tabs highlights all
  three"). Active state derives from the path, never from local state.
- **TanStack Query** with a generated typed client from OpenAPI in CI (a type drift is a build
  failure, not a runtime surprise). `staleTime` 30 s for aggregates, 5 s for live views,
  `gcTime` 15 min. Every query key includes account, scope and environment so switching any of
  them cannot show another context's cached numbers.
- **Filters live in the URL** (`useSearchParams`), so a manager can send a colleague a link to
  exactly what they are looking at, and a reload preserves it.
- **One `<DataBoundary>`** component wrapping the four states, taking the reason code and
  rendering the `next` action. Screens do not hand-roll error handling.
- **Aggregates only** in list and dashboard views; drill-down is an explicit navigation into a
  narrow window, which is also where the audited raw read happens.
- **Live tail over SSE** with an explicit buffer cap and a "paused, N behind" state rather than
  unbounded memory growth.
- Charts: `recharts` with fixed dimension sets; no chart renders a dimension that the rollup
  does not carry, so a chart can never trigger a raw scan.

## Performance rules

| Rule | Why |
|---|---|
| Production build served by nginx, gzip + immutable hashed assets | The dev server was the reported slowness |
| Route-level code splitting; graph, editor and charts lazy | First paint should not carry the graph view |
| No barrel imports from icon or UI libraries | Hundreds of modules for three icons |
| Skeletons match final layout | No layout shift, no perceived "reload" |
| One bootstrap request on load, then nothing until interaction | Today's login does N parallel calls, any of which can fail |
| Virtualised tables past 200 rows, `content-visibility` on long lists | 20k-member directories |

## Test plan for the console

1. **Contract test**: OpenAPI → TS types generated in CI; drift fails the build.
2. **Persona smoke test** (Playwright): for each of member · dl_admin · security_admin ·
   finance_admin · auditor, seeded with fixtures, visit every route in the manifest and assert
   zero console errors, zero unhandled rejections, no request over 400 except deliberate
   403 checks, and that each screen reaches `data` or a *purposeful* `empty`.
3. **Authorization test**: for each persona, one route they may not see returns 403 with
   `module_forbidden`, and one neighbouring org unit returns `scope_outside_grant`.
4. **State test**: force loading, empty, error and data for the ten most-used screens.
5. **Regression test for the login class**: no session persists after a failed onboarding; a
   reload after a failure returns to a clean login with the reason still displayed.
