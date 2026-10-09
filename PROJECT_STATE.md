# Project state

Single source of truth for where development stands. Read at the start of every session,
update at the end of every session. Governed by `.cursor/rules/project-state.mdc`.

**Last updated:** 2026-10-09 · session 37 (public repository scrub)

---

## Current position

**Session 37 prepares this tree for a public research repository.** Internal MCP servers,
directory usernames, and sample credentials are not in the tree. The adapter ships only
`examples/mcp/demo_server.py`. The console home and Discovery screens show the harness
vocabulary the ledger already stores. The public pages are `README.md` and `docs/`.
No module moved to `OK`. The next engineering slice is unchanged: apply `0019`–`0024`
to a real PostgreSQL and run `tests/sql/invariants.sql`.

**Session 36 implemented F1 (`design/prompts/f1-ledger-schema.md`): the schema the MVP is.**
Two revisions, four runtime-identity tables, the partitioned content-free action ledger, the
typed `aap.action.v1` envelope, and the tests that keep each vocabulary's two copies in step.
No endpoint, no collector, no screen — the prompt forbids them and this slice honours that.

**`0023_agent_runtime_identity` adds the entity the registry never had.** An agent is a
definition; an *instance* is a thing that can read a token off a filesystem, and the threat
model needs the second one. `agent_instances` carries a mandatory `human_member_id` and
`root_human_basis`, so `design/14` §1 — no agent action without a human root — is a NOT NULL
rather than a convention. `agent_sessions` carries taint, and a trigger refuses
`tainted → clean`, because that is not a state transition, it is the erasure of a security
fact; a clean context window is a new session, not an edit. `agent_tasks` carries an intent
*digest* and no intent. `delegations` is policed by a trigger rather than a CHECK because
attenuation is a statement about two rows: a child holds a subset of its parent's authority,
never more (threat model AP-6).

**`0024_agent_actions_ledger` is `aap.action.v1` as a table.** Monthly range partitions on
`occurred_at` so retention is a `DROP TABLE` rather than a delete across hundreds of millions
of rows; append-only by trigger, with no exception for a late correction; RLS on the parent
*and* on every partition, because a policy on the parent covers nothing that names
`agent_actions_202610` directly. `enforcement_grade` is NOT NULL and `unknown` maps to `E`
through one function, so no query can count the population we cannot see as protected.
`agent_action_receipts` is separate and unpartitioned because Postgres requires the partition
key in a unique constraint on a partitioned table — `UNIQUE (org_id, event_id, occurred_at)`
would cheerfully accept a retried event whose timestamp had been corrected in flight, which
is precisely the duplicate a retrying collector produces.

**Content-freedom is enforced by the schema, not by review.** There is no column for a
prompt, a completion, a file body, a full path, a raw command line or a raw tool argument,
and `agent_action_facets_valid()` makes an unrecognised facet key a constraint violation
rather than a convenient extension point. `design/15` §9's `payload_ref` and
`provenance.signature` are deliberately absent: the MVP has no audited-reveal path for a
pointer to resolve through, and collector signing keys are V1. The envelope *rejects* both
rather than ignoring them, because a field quietly discarded cannot be shown to a security
reviewer.

**Three things were found by writing this, not by reviewing it.**

1. `agents` and `agent_versions` had no `UNIQUE (org_id, id)` in any migration, although
   `app/db/models/registry.py` has declared one on `agents` since `0001`. Every composite
   tenant-safe foreign key in `0023` depends on it, so `0023` adds both, each guarded by a
   `pg_constraint` lookup because `ADD CONSTRAINT` has no `IF NOT EXISTS`.
2. `app/db/models/auth.py` was written for `0022` and never exported from
   `app/db/models/__init__.py`, so `AuthProvider` and `AuthSession` were absent from
   `Base.metadata` and invisible to `test_model_drift.py` — the one test whose whole job is
   to notice. A model that is not registered is not checked, and the failure mode is
   silence. Now exported, and the drift test walks the other direction as well.
3. The first draft made the effective grade a stored generated column. A generated column on
   a partitioned parent must be reproduced on every partition, and the maintenance path
   builds partitions with `CREATE TABLE (LIKE ...)` and fills them with `INSERT ... SELECT
   *`, which cannot write one. It is a function instead, which keeps the rule in one place
   without breaking the mechanism that keeps the table droppable by month.

**What was verified, and what was not.** `ruff check` and `ruff format` are clean across all
308 files, strict `mypy` is clean on the six files this session wrote, and the full API suite
is **1152 passed, 177 skipped**, including **52 new unit tests** in
`tests/unit/test_agent_actions.py`. Every skip is an integration test. This machine still has
**no Docker, no PostgreSQL and no `psql`**, so: `0023` and `0024` are **written, not
applied**; the nine new sections in `tests/sql/invariants.sql` are **written, never
executed**; and the three reverse-direction checks added to `test_model_drift.py` have never
run. None of that is a pass.

**One thing found and deliberately not fixed.** `mypy app` reports **10 errors**, all of
them in `auth/repository.py`, `auth/service.py`, `bootstrap/service.py`,
`members/repository.py` and `access/repository.py` — three unused `type: ignore` comments, a
`members_service.MemberProfile` that does not resolve, two `PropComparator.any(str)` calls
and three reads of `Result.rowcount`. None is in an F1 file and F1 did not introduce any of
them; they are left for the sessions that own those domains. Worth noting *why* they
survived: session 35 reported a passing type-check, and it was `tsc` over `services/web`.
The API's type-check and the console's are two different commands, and only one of them is
in anybody's habit.

### Next, and what blocks it

**The same missing host F0 and F2 both named.** F1's gap closes the same day theirs does:

1. Apply `0019`–`0024` to a real PostgreSQL, from empty and from an existing database at
   `0022`. Downgrade `0024` one revision, re-upgrade, confirm a single head.
2. Run `tests/sql/invariants.sql`. Sections 15–23 have never executed, and §23b is the
   first **behavioural** RLS test in the project: it creates a throwaway unprivileged role,
   because the application connects as a superuser and every policy in the schema is
   therefore inert at runtime (Q-015). Presence of a policy has never been evidence that it
   bites, and until now nothing in this repository tested the difference.
3. Run `tests/integration/test_model_drift.py`. Its new checks are the ones most likely to
   find something: every migrated table has a model, primary keys agree — the ledger's
   composite `(id, occurred_at)` is the case that matters — and no NOT NULL column without a
   default is missing from a model.
4. M3 owns ingestion. Nothing writes to `agent_actions` yet and `app/domains/agent_actions`
   is deliberately `schemas.py` only, so the collector and the table are written against one
   definition rather than two that drift.
5. Clear the 10 `mypy app` errors in the `auth`, `bootstrap`, `members` and `access`
   domains, and put `mypy app` in CI beside `tsc --noEmit`. Neither is expensive; one of
   them is currently only run by whoever remembers.

**One claim this session will not make.** The prompt lists `inv_new_tables_rls` as "cross-org
reads and writes fail for every new tenant table". §23b asserts exactly that for an
unprivileged role, and that is the strongest honest form of it until Q-015 is answered: the
test proves the policy, not the deployment.

---

## Previous position — session 35

**Session 35 implemented F2 (`design/prompts/f2-ui-structure.md`).** The console now has one
navigation, authored by the server, and a landing page that is a ledger rather than an
assurance dashboard. No migration was written and no table changed; this is UI structure
and the bootstrap contract that feeds it.

**Navigation moved from the browser to the server, and there is only one of it.**

- `bootstrap/service.py` holds two manifests — `_LEDGER_NAVIGATION` and
  `_ASSURANCE_NAVIGATION` — and `AAP_PRODUCT_MODE` (default `ledger`) selects which one a
  request gets. Entries are then filtered by the member's permissions, the account's
  licensed modules and the install's capability flags, and a group emptied by that
  filtering disappears rather than rendering a heading over nothing.
- `AAP_ASSURANCE_CAPABILITIES` is a comma-separated allowlist and **defaults to empty**, so
  a fresh ledger install shows the ledger, agents, admin and MCP — not the accreditation
  product. An operator names the surfaces they want back rather than hiding the ones they
  do not.
- `Rail.tsx` and `TopBar.tsx` are **deleted**. Both were orphaned and neither was reachable,
  but their existence is how two navigations came to disagree about which product this is.
  `inv_single_nav_source` now fails the build if either returns.
- `product_mode` is branched on in exactly one file, `HomeRoute.tsx`, which lazy-loads
  either the ledger home or the assurance home. Both are separate chunks, so neither
  product downloads the other's landing page.

**The four states are one component, and a project is a filter.** `DataBoundary` owns
loading, empty, error and data; `ErrorState` became a leaf that renders the `reason` and
`next` the F0 error contract already returns, instead of inventing its own copy. In
`ObserveSuiteLayout` the boundary wraps **only the project selector** — the `<Outlet />`
sits outside it, so a slow or failing project list degrades the filter and never becomes a
wall in front of the ledger.

**Every number on a ledger screen carries its grade.** `EnforcementGrade` and `GradedCount`
implement D-069 as UI: A–E with the claim each letter supports on hover, and an ungraded row
rendered as E labelled "ungraded" rather than blank. The ledger home's four slots — coverage
by grade, recent high-risk actions, unregistered collectors, credential exposures — render
em dashes and name the slice that will fill them. **Three of the four have no data and say
so.** A zero would claim we looked and found none.

**Two defects were found by enforcing the invariants, not by review.**

1. `SessionSummary` in `src/api/types.ts` resolved to nothing. F0 added an auth-side
   `SessionSummary`, FastAPI disambiguated both to fully-qualified names, and the alias
   still named the short one — invisible because `openapi.json` was a snapshot taken
   before that change. **This is D-049's conditional guarantee failing in practice for the
   first time**, and it is exactly the failure mode the `web` row is `WIP` for: `check:api`
   proves a path is in the snapshot and nothing proves the snapshot is current.
2. `lucide-react` deep imports type-check as `any`, because the package ships one
   declaration for the barrel and none for the ~1,600 icon modules. That is the real reason
   the barrel import persists everywhere — it is the only one that types.
   `src/types/lucide-icons.d.ts` declares them, so obeying `inv_no_lucide_barrel` no longer
   costs type safety.

**The three failures F0 handed over are closed.** The tuple/list assertion in
`test_agent_actions.py`, the 13 files barrel-importing `lucide-react`, and the two
`react-refresh` lint errors in `EnforcementGrade.tsx` — the last fixed by splitting the
vocabulary into `grades.ts`, named to avoid a case-only collision that resolves to one file
on Windows and two on Linux.

**What was verified, and what was not.** Run and passing: 1,151 API unit tests (25 of them
new, on navigation), `npm run check:api`, `npm run check:runtime` across 168 files,
`tsc --noEmit`, `eslint --max-warnings 0`, and a production `vite build`. **Not run:** this
machine still has no Docker and no PostgreSQL, so integration tests skip and `0022`–`0024`
remain unapplied; and **the console was never loaded in a browser this session.** Every
claim above about navigation and the home screen is a claim about source and types, not
about pixels. `audit-ui.mjs` gained the `/discovery` route but needs a running app to
execute.

### Next, and what blocks it

**F0, F1 and F2 are now written; none of the three is proven against a running system.**
The next slice by D-073 is **M1 (identity chain)**, and it is not blocked by this session.
What is blocked, and by the same missing host F0 named:

1. Apply `0019`–`0024` to a real PostgreSQL. F1's `0023`/`0024` are written and chain
   linearly off `0022`; none of the six has run.
2. Load the console in a browser against a real bootstrap and confirm the three things
   only a browser can show: the ledger navigation renders in the order the manifest
   declares, `product_mode=assurance` restores the full product, and no screen reaches a
   dead route. Nothing in this session's verification touches any of that.
3. Run `audit-ui.mjs` and the Playwright certification (no `e2e/` directory exists) across
   `member` and `security_admin`, including the new `/discovery` route.
4. **Make `openapi.json` regeneration a CI step that fails on a diff.** This session found
   the first real instance of the drift D-049 predicted, and it was silent. Until this
   exists, `web` contract integrity stays `WIP` and the guarantee stays conditional.

Two pieces of F2 are deliberately unfinished rather than missed. The legacy assurance
screens still hand-roll their loading and error states; `inv_data_boundary_exists` names
only the two ledger entry points, because converting the rest is not this slice and a
tree-wide assertion would have been satisfied by a token import. And three of the four
ledger home slots stay empty until M3 ingest and M4 discovery give them something true to
say.

---

## Previous position — session 34

> The three open failures listed at the end of this section were **closed by session 35**.
> They are left here as written because this is what was true when F0 closed.

**Session 34 implemented F0 (`design/prompts/f0-console-contract.md`).** Authentication,
session handling and error rendering are now structural. The browser no longer talks to an
identity provider, no longer holds a token, and no longer decides which providers exist.

**What moved from the browser to the server.**

- `GET /v1/auth/config` answers which sign-in methods exist, per request, from
  `auth_providers`. `VITE_OIDC_*` is gone from `services/web/src` and the login screen
  renders buttons from the response — with a sentence naming the missing configuration
  when there are none, instead of a button that does nothing.
- The authorization-code + PKCE exchange happens in `app/auth/providers.py`. The id token
  is verified there (signature, `iss`, `aud`, `exp`, `nonce`, 60 s skew), each failure with
  its own reason. The old path decoded it with `atob`, which reads a signature it cannot
  check.
- The session is a row in `auth_sessions` behind an opaque `HttpOnly; Secure; SameSite=Lax`
  cookie, with refresh, logout, list and revoke. It replaces a token in `sessionStorage`,
  which could not be revoked or listed and survived logout in other tabs.
- `GET /v1/session/bootstrap` returns member, account, access, **navigation manifest**,
  modules, capability flags and freshness in one response. The shell renders from it.

**The bypass is gone, not relocated.** `AAP_DEV_AUTH_BYPASS` and `Bearer dev.<email>` are
deleted from `config.py` and `deps.py`. Development sign-in is a `development` row in
`auth_providers`, refused unless `AAP_ENVIRONMENT=development`, which issues a real session
for a real member on the `localhost` domain. See `inv_dev_provider_requires_dev_mode`.

**Three defects were found by writing the tests, not by review.**

1. `normalise_email` required a dot in the domain, which made `someone@localhost`
   unresolvable — so the development provider the prompt mandates could never have signed
   anybody in. The rule was a guess; the provider's `email_domains` allowlist is the real
   check.
2. `GET /v1/auth/config` hung indefinitely when Postgres was unreachable, because the
   engine had no connect timeout. That is the one call the console makes before anybody is
   signed in, so a database outage rendered as a spinner that never resolves. Now
   `db_connect_timeout_seconds` (default 5) bounds it and the endpoint answers
   `upstream_unavailable`.
3. An empty `services/api/AGENTS.md` (0 bytes, created 2026-09-18) shadowed the real
   coding contract for anything walking up the tree, including
   `test_layer_order_matches_agents_md_chain`, which had been failing on it. Deleted.

**What was verified, and what could not be.** This machine has **no Docker and no local
PostgreSQL**, by the owner's decision to run locally for now. So: the unit suite and
`npm run check:runtime` were run and pass; the integration suite **skips**, migration
`0022` is still **written, not applied**, and the Playwright work in the F0 test plan was
not started (no `e2e/` directory exists yet). Those are gaps, not passes.

**`tests/smoke/` is knowingly broken by this change.** It authenticates with `X-Org-Id`
under the old bypass, so every request it makes now returns 401. Migrating it needs a
running stack to verify against; the module docstring says so rather than pretending.

### Next, and what blocks it

**A server is being provisioned.** The owner is supplying one host to deploy against, which
is what unblocks everything F0 could not prove. Until it exists, none of the following may
be marked as passing, because none of it has run:

1. Apply `0019`–`0022` to a real PostgreSQL and re-verify the application status of all
   four. `0022` is the one F0 depends on.
2. Run `tests/integration/test_auth_sessions.py` — forced RLS on both auth tables, zero
   model/migration drift, and the row half of `inv_no_session_without_member`.
3. Seed one `development` provider row and complete a sign-in end to end: cookie issued,
   bootstrap answers, logout revokes server-side, next request is 401 `session_expired`,
   client recovers.
4. Migrate `tests/smoke/` to console sessions and run the sweep — the check that catches
   routes no typed test touches, which is why it was written in the first place.
5. Playwright: `member` and `security_admin` across every licensed route, zero console
   errors, every screen reaching `data` or a purposeful `empty`. No `e2e/` directory
   exists yet.

**F1 and F2 are being implemented in parallel by another session** (agent actions ledger;
navigation, ledger home, enforcement grades). That work builds on F0's `Shell.tsx`,
`useBootstrap.ts` and `DataBoundary` rather than replacing them. It owns three open
failures as of F0 closing, none of them F0's, and F0 did not touch them on the owner's
instruction:

- `tests/unit/test_agent_actions.py::test_the_migration_history_has_exactly_one_head`
  compares `get_heads()` to a tuple; it returns a list. The head itself is correct
  (`0024_agent_actions_ledger`), so this is the assertion, not the migration history.
- 13 files barrel-import `lucide-react` against that session's new `inv_no_lucide_barrel`.
- Two `react-refresh/only-export-components` errors in `EnforcementGrade.tsx` fail
  `npm run lint`.

---

## Previous position — session 33

**Session 32 re-opened the design and materially changed it.** The owner asked for a deep,
sourced research pass rather than more implementation, with one explicit question — *how do
we handle Cursor and Claude when they own their own gateway?* The answer turned out to
invalidate two of the design's load-bearing assumptions, so this is a revision and not a
review. Seven new documents (`design/12`–`18`), 108 cited sources, eleven decision records
(`D-08`…`D-18` in the design-set namespace), four new generated diagrams, and amendment
headers on `01`–`08` and `11`. **No product code was changed** beyond removing a hardcoded
employer domain from three dev-bypass paths.

**The two findings that changed the architecture.**

1. **Both enforcement points were off the path of the reference incident.** On 25 April 2026
   a Cursor agent read a long-lived token off its own workspace filesystem, built a `curl`
   command, and called a `volumeDelete` GraphQL mutation — destroying a production database
   and its volume-level backups in nine seconds `[B-01][B-02][B-03]`. That path is
   `fs.read → shell.exec → net.http`. It is not a model request and it is not an MCP
   `tools/call`, so the model gateway (`05`) and the MCP gateway (`06`), fully built and
   fully deployed, would have seen nothing and stopped nothing. The MCP gateway is not
   wrong; it is **too narrow to be the top-level abstraction**. Hence D-066.
2. **Cursor's model traffic resolves inside Cursor's cloud.** Base-URL routing does not make
   us an egress control for Cursor — their backend is the intermediary `[B-41]`, which also
   means our data plane must be internet-reachable rather than outbound-only. Every prompt
   DLP claim for Cursor was therefore unsupportable and has been withdrawn. What *is*
   supportable for Cursor: **Grade A** MCP mediation (Cursor is a direct MCP client, and the
   enterprise allowlist **replaces** rather than merges with user config `[B-42][B-43]`),
   **Grade B** hook interposition `[B-33]`, **Grade C** configuration attestation, **Grade D**
   usage reconciliation `[B-39]`. Hence D-070 and the grading scheme in D-069.

**The honesty mechanism that came out of it.** Every control now carries a grade: **A**
mediated, **B** interposed with a real veto, **C** vendor-enforced and attested by us, **D**
observed afterwards, **E** not covered. A Claude Code `PreToolUse` hook returning exit 2
genuinely prevents the call `[B-31]` — that is Grade B, not "configuration". A coverage
number without its denominator does not ship. This is a mandatory column on every decision
row, and `unknown` counts as E.

**The MVP was replaced, not re-sequenced.** The ten-phase plan delivered a security outcome
around phase seven and built three commodity layers on the way `[B-16][B-18][B-29][B-30]`.
The replacement is a **read-only agent action ledger** across Claude Code, Cursor and
Copilot: `shell.exec`, `net.http` and `fs.read` observed, every row graded, plus shadow-agent
and credential-exposure discovery. It installs in days, needs no architecture review, adds
no latency to anything, and produces the customer's own evidence that they need enforcement
next. Enforcement and credential brokering follow in V1 — sold against data the customer
generated, not against a slide.

**What survived untouched, because it was already right:** the org-unit tree and closure
table; permission separated from visibility with one `visible_paths` rule; residency as a
property of an attested endpoint and never of a model name; the measured false-positive gate
before any DLP rule may block; pinned MCP snapshots with digest comparison and quarantine
(a direct defence against `CVE-2025-54136` `[B-06]`); "an unparseable argument is a deny";
and declared-versus-observed composition drift, which is the most defensible idea in the
repository and is now the V1 differentiator rather than a phase-9 feature.

**Session 33 converted the research into an executable development program.** Q-L and Q-M
are resolved as the research recommended: read-only ledger first; Claude Code first and
Cursor before the MVP demo. `design/prompts/README.md` is now the only sequence:
F0 → F1 → F2 → M1 → M3 → M4 → M2 → M5 → V1 → packaging. The old `phase-00`–`phase-09`
files are retained with non-executable warnings. A new F1 prompt owns the real additive
schema from Alembic head `0022`; no prompt may recreate a tenant root, agent registry,
auth-session table, MCP registry or Observe pipeline.

**Next slice: F0 console contract.** Finish the API/web behavior around existing revision
`0022_auth_sessions_and_providers`: server-side OIDC exchange, cookie session, one bootstrap,
typed reason errors and project-as-filter. In parallel only, F1 may write `0023`/`0024`
runtime-identity and action-ledger migrations. M3 is the first commercial falsification
gate: if Claude Code and Cursor cannot map into one content-free `aap.action.v1` contract,
stop and revise the capability abstraction.

---

**Paused as of Session 31 (2026-09-21).** The owner set this product idea aside after
concluding the agent-governance market is closed to a solo part-time founder, and redirected
effort to career work outside this repository. Session 32 revisits that conclusion with
evidence: the market for *AI gateways* is indeed closed `[B-16][B-18][B-29][B-30]`, but
cross-vendor agent **action evidence** with graded enforcement is not yet owned by anyone
(`design/16`). That does not make it buildable by one part-time person — it makes the
narrower ledger wedge the only version worth attempting.

**Session 30 wrote the design, not code.** `design/` now holds eleven specification
documents, eleven generated Excalidraw sketches (with SVG/PNG previews and a layout
validator that reports zero defects), and ten paste-ready phase prompts in
`design/prompts/`. `docs/architecture/AI_CONTROL_PLANE_PLAN.md` is the approval summary and
links into that set. **No module status changed and no code was modified**, per the owner's
instruction to plan before developing.

What the design settles: five deployment modes behind one `accounts.deployment_mode`; one
org-unit tree that models business units, departments, teams **and distribution lists** with
a closure table (the 30 DLs × 200 members shape); per-account `auth_providers` with five
onboarding modes, so login stops being a build-time constant; permission separated from
visibility with one `visible_paths` rule every activity/cost/risk query intersects; the
honest residency model (a property of an attested endpoint, never of a model name); ten
ordered fail-closed checks for `tools/call` with argument-level rules; a DLP action matrix
with reversible tokenisation and a measured false-positive gate before any rule may block;
a ClickHouse activity pipeline sized for 3 000 events/s with rollups instead of raw scans;
and an expand→backfill→dual-read→contract migration whose grants revision (0027) aborts the
deploy on any effective-permission difference.

**Recorded as D-064 and D-065.** D-065 reverses the phase order in the earlier plan: MCP
enforcement moves from first to fifth, behind identity and authorization. Nothing in the MCP
design is reduced.

**Next slice:** the owner answers D-A … D-G in `design/README.md`, then Phase 0
(`design/prompts/phase-00-stabilise-console.md`) is pasted as its own session. Phase 0 is
the login/session/error work that fixes "unable to login with Entra ID" and "Something went
wrong · Try again" properly rather than per screen.

---

**The post-rebuild 403 failure is fixed.** The browser no longer reads, stores or sends an
organization UUID; development resolves the sole account server-side, and production maps
the verified Entra tenant claim to the account. Profile shows the account display name
instead of internal tenant identifiers. People & Teams now supports employee invitations
and hierarchical team creation. A pending employee activates on first verified directory
sign-in, which binds the immutable issuer/subject; an uninvited employee in the same Entra
tenant remains denied. The account isolation key remains internal per D-034/D-063.

**The console has one live route per Activity concept and no runtime Nexus fixtures.**
Exact-match side-nav state separates Overview, Executions, Sessions, Traces, People and
Live tail; execution/session/trace rows deep-link to live Observe details, and the compact
execution graph renders only the selected run's observations, events and edges. Profile is
a first-class route. Entra OIDC PKCE auto-starts, API discovery maps issuer claims to the
account/member, and the development fallback maps the current net ID without an org picker.
The MCP registry/detail, model routing, people hierarchy, Platform Keys and security audit
screens are Nexus-styled and API-only. The adapter's only shipped server is the
synthetic `demo-mcp`; deleted fixture modules cannot be imported at runtime.

**Identity now survives both enforcement paths.** Migration `0018` is applied and a
PostgreSQL integration test proves a personal Platform Key can bind only to a member in the
same account and returns that member after verification. MCP decisions, daily capability
usage and OTLP spans carry `member_id`; the signed model-routing snapshot carries it into
the Go gateway, whose audit queue exports content-free routing/data decisions to the
append-only audit API. Both gateway and MCP adapter scan raw and decoded JSON so escaped
secrets do not bypass pre-dispatch blocking. Provider secrets stay behind vaulted
Connections; agent code receives only an AAP gateway URL, route alias and Platform Key.

**Honesty limits:** Q-013 remains open for the production SaaS issuer and refresh-token
lifecycle. Docker Desktop stopped before the final Go escaped-JSON hardening rerun and
gateway/MCP image deployment; the owner chose to leave the verified code ready rather than
restart Docker now. The full Go suite passed immediately before that last scanner hardening.
API unit tests (33), workload Postgres integration tests (11), MCP adapter tests (6), web
lint and production build pass.

**MCP deployment is live against the synthetic demo server.** Earlier notes that named
internal package and source hosts were removed before publication; those hosts are not
part of this repository.

**Next slice:** finish Q-009 customer-account bootstrap and Q-013 production Entra
configuration, then implement consented Entra/SCIM directory synchronization for joiner,
mover and leaver updates without mapping directory groups directly to protected roles.

---

**Agent Execution Observability Phases 1–12 are implemented and Phase 13 local
certification is in progress.** Observe is now the canonical detailed execution plane:
PostgreSQL holds execution/session/user metadata and durable outboxes, ClickHouse holds
typed observations/events/edges and aggregates, object storage holds encrypted protected
content, and Operations receives a content-free projection.

The `aap-trace` Python and TypeScript SDKs cover LangGraph, LLM streaming, tools, SDK,
HTTP/database, MCP and A2A boundaries. The console has session/execution deep links, live
graph/tree/timeline views, typed inspectors, protected payload access, user/execution
analytics and sampling controls. Enterprise redaction, tenant/project query binding,
retention/legal hold and air-gap endpoint validation are implemented.

**Next slice:** finish Phase 13 production certification: fresh-volume rebuild, migration
upgrade/restart recovery, shell/PowerShell reset-script certification, integration/load
budgets and published limitations. Local implementation is exercised by the deterministic
FOSS Remediation execution. Production certification remains blocked by Q-013/Q-014/Q-015
(console login, authorization roles and a non-superuser application database role).

**Draft queued after certification:** a repository and market audit recommends evolving the
existing Go Router into an Assurance-Native Agent Gateway with modular LLM, MCP and A2A
data-plane paths. Routing and caching are supporting capabilities; the proposed moat is an
approved-agent-version → signed capability policy → inline enforcement → Observe
reconciliation → evidence/revocation loop. This remains a design proposal pending Q-023;
no implementation decision, dependency or module status changed.

**Consolidated platform redesign draft:** `docs/architecture/account-access-console-redesign.md`
now joins account identity, RBAC/ABAC, provider connections, Platform Keys, unified
human/agent activity, governed model/MCP/A2A/tool/data registries, MCP user/team/agent
grants, gateway adoption/enforcement and the six-destination console in one tracked plan.
Registry, observed inventory and marketplace are separate. “Organization” leaves ordinary
product language while `org_id` remains the tenant, billing, vault and isolation root;
literal removal would contradict D-006/D-034 and invalidate RLS, gateway and Observe
contracts. Session 25 implemented the account/access/credential/MCP-registry/audit scope of
that draft. Session 26 records the owner's approval of the remaining visual migration and
backend sequence as D-060; gateway implementation is still gated by Q-023.
A commercial assessment of that draft prices the first licensed release as an
account-level platform (not token resale): $18k–$320k list ACV, ~$61M net ARR
at 1,000 enterprise-weighted logos with ~77% gross margin. No SKU, licence
schema or module status changed.

The redesign now has a self-contained interactive approval prototype at
`docs/design/platform-ui-approval.html`, covering the six-destination console plus
agent, execution, MCP, connection, Platform Key, people/access/audit and profile
detail surfaces. `../agent-assurance-hld.drawio` now has 17 pages; pages 15–17 define
service communications, state/storage ownership and the identity → enforcement →
trace → evidence path. D-060 now makes them implementation inputs; Activity/MCP/People
Nexus layouts and Entra login UI are deployed; live Observe/MCP API wiring remains.

## Previous position — session 26

**The Nexus console replacement is in progress and its first deployed slice is live.**
Session 26 replaced the old rail/top bar with the Nexus 260px responsive glass shell and
six-destination information architecture, routed it to the live Agents, Observe, Router,
MCP, connections, access, audit and assurance domains, and added live Nexus-style Control
Center and Platform Keys screens. Migration `0017_account_access_registry` is **applied**
and **54/54** account/access/MCP/audit integration tests pass against disposable Postgres.

## Previous position — session 18

The complete runtime suite was deployed locally. Compose runs the API, web, gateway,
collector, Observe ingest/worker/query, Prompt, Evaluate API/worker, PostgreSQL, Redis
and ClickHouse; every configured health check passed. API migration head is
`0016_router_runtime_hardening`, service-owned migrations are applied, and the OTLP path
was proven collector-to-console.

## Previous position — session 16

**Gateway can pull signed router config from the control plane.** When
`GATEWAY_CONFIG_URL` is set, the Go gateway polls with `If-None-Match`, verifies a
pinned ES256 public key (PEM or file — never from the endpoint), checks AAP response
headers against parsed JSON, and keeps the last good snapshot on failure.
`GATEWAY_CONFIG_REQUIRED` fails fast at startup; file mode unchanged when URL is unset.
Gateway tests (incl. `-race`) pass via Docker; host has no local `go` on PATH.

## Previous position — session 15

**The console the owner has been looking at was never the console that was built.** The
`web` service had no source mount: it baked a bundle into its image and nginx served that
frozen copy, while every other service reloaded from disk. The image dated from 13:22 the
previous day, before all of that day's frontend work. Four screens "did not work" because
their routes and nav entries were genuinely absent from the bundle being served. The
compose file already carried a comment explaining this exact failure for `migrate` — "the
source mount is load-bearing, not a convenience" — and the lesson had not been applied to
`web`.

That was the visible failure. Two worse ones were underneath it.

**Fifteen of the console's fifty-three request paths pointed at routes that never
existed.** `/v1/findings` for `/v1/assurance/findings`, `/v1/sla/...` for `/v1/slos/...`,
`/v1/evidence/events` for `/v1/evidence`. Findings, Evidence, Policy, Service levels,
Attestations, the BOM tab, blast radius and release impact were all calling dead URLs.

**Roughly a dozen response types had drifted from the API.** `PolicyVersion` declared
`version`, `digest`, `signed_by` and `signature_status`; the API returns `semver`,
`rules_digest` and `published_by`, and has no signature status at all. `MeasurementOut.value`
is a string, so the SLO chart was doing arithmetic on strings and drawing nothing.

Both were invisible for the same reason: `src/mocks` was a second, hand-written account of
a 125-route API, and it was wrong in the same places. The console looked completely healthy
in mock mode. **A fake that agrees with your mistakes is worse than no fake, because it
removes the feedback that would have caught them.** It is deleted — 2,629 lines (D-050).

The repair is structural rather than a list of fixes. `openapi.json` is now generated from
the running API and `schema.d.ts` from that, so response types are derived rather than
retyped (`Wire<"Name">`). `npm run check:api` reads every `/v1/` literal out of the source
and every route out of the spec and refuses to build on a mismatch — a check a type system
cannot perform, because a path is a string and the two halves live in different languages.
`tests/smoke/sweep.py` calls all 85 readable routes against the seeded estate.

The sweep earned itself on its first run: `column c.name does not exist` in
`materiality/repository.py`, raw SQL naming `customers.name` when the column has been
`display_name` since migration 0002. Two queries, both 500ing, neither covered.

The full suite also turned out to contain a test that could only pass in the afternoon:
`test_drift_detection_on_run_step` mixed a `NOW` pinned to 12:00 UTC with
`datetime.now(UTC)`, so `started_at` preceded `ended_at` for any run before midday. It has
been failing every morning and passing every afternoon, and the error message said nothing
about the clock.

**Measured after the repair:** 653 passed, 4 skipped. Frontend typecheck and lint clean,
build passes with the path check in the pipeline, 56 of 56 console paths resolve against
125 routes, 78 of 85 readable routes return 2xx with zero server errors. The seven that do
not are correct refusals — a 409 for an event not yet sealed, 422s for genuinely required
query parameters.

`tasks.md` is new and is the place to look for what is next. `agent-assurance-hld.drawio`
gained five pages (10–14) covering tracing, change review, the routing enforcement
boundary, contract integrity and suite packaging; it had been describing five fewer modules
than exist since 13 September.

**What has not changed: the console still cannot approve a release, and no agent can
report.** Those remain the two things standing between this and a real product, and both
are now written down with their consequences in `tasks.md`.

## Previous position - session 14

**The product now has all four of the things the owner described it as: a langsmith, a git,
a proxy, and a test harness.** Four capabilities were built in parallel this session and all
four are live against the seeded estate. The design pack in `docs/design/` was implemented
rather than left on the shelf, with three of its recommendations overridden on the evidence
(D-043 through D-046).

`composition` **makes an agent's parts reviewable.** The descriptor now carries tools, rules,
skills, subagents, configs, MCP servers, model policy, memory sources and guardrails, each
with a *stable identity* rather than a list position — which is what makes a diff readable
instead of index churn. `aap extract` walks a repo and finds LangGraph graphs, tool
registrations, MCP config, Cursor rules and skills, and it reports what it could not
determine instead of guessing. Reconciliation compares all of that against what the runtime
actually did and writes findings for observed-but-undeclared, declared-but-never-observed,
and model use outside policy. **That disagreement is the most valuable thing this product
computes**, and it is the one check nobody else is positioned to make.

Rules were the hard part, because rules are natural language and rule 5 forbids storing
prompts. The resolution is a digest plus a source reference plus bounded extracted
obligations, held under a 512-byte database CHECK. The platform can therefore diff and
review a rule without ever becoming a store of customer prompt text.

**The review brief is the answer to the owner's actual problem** — that the people reviewing
AI-written agents no longer have the depth to know what changed. It is deterministic
templates over the semantic changeset, ordered re-accreditation first, every sentence
carrying the change path and the rule id that produced it. Approval binds to the reviewed
descriptor digest, so an approval cannot silently carry to a descriptor nobody read.

**Residency is enforced in the gateway, audited here.** Model catalogue, allowed-model
resolution from the existing cross-border ladder, emitted gateway configuration, a
pre-dispatch decision endpoint, and drift detection over observed models. Unknown model
denies in production and raises a finding — that is the case the auto-router guarantees will
happen and the one the whole feature turns on.

**Probes decide by oracle, never by a model's opinion**, and the screen makes that
distinction impossible to miss. Rule-gap analysis maps regulation controls to obligation
templates and reports what an agent is missing, with remediation hints.

**The console is rebuilt to the owner's reference design** — light throughout, the dark rail
gone. Two cards from the reference were deliberately dropped rather than filled with
invented numbers, which is the right call on a governance dashboard.

**A cycle was caught and the rule behind it is now enforced.** Four parallel agents produced
a module-level import cycle between `composition` and `assurance`; the suite passed anyway.
Layering now lives in `app/domains/layer_order.py` and a test parses the real import graph
(D-047). Two domains had been missing from the documented chain entirely.

**Not done, and it is still the same gap.** Nothing can report a run except the seed. The
ingest endpoint takes only the development org header, so a LangGraph agent using the Cursor
SDK has no credential to present, and the probe runner can only reach a synthetic target for
the same reason. Everything above is exercised against seeded data. **The console is also
read-only: it has no mutations at all, so a release cannot actually be approved from the
review screen** — which is the one workflow the review brief exists to serve.

**Run tracing is live end to end.** Migration `0009_run_steps` is applied and reversible.
The `operations` domain ingests `StepReport` rows on `POST /v1/operations/runs`, serves
`GET /v1/operations/runs/{run_id}` (`RunDetail` with self-time and critical path) and
`GET /v1/operations/agents/{agent_id}/graph` (`ObservedGraph` from consecutive node
steps — not `graph_nodes`). The demo estate was backfilled with ~100k step rows via
`seed.generate` when `run_steps` was empty. The console tracing screens now match live JSON.

**The product now sees the agents as well as governs them.** A new `operations` domain
records what agents actually did — runs, cost, latency, tool calls, MCP servers — and the
console is rebuilt around joining that to the governance record it already had. That join
is the thesis. A runtime dashboard shows cost and latency; a governance tool shows
approvals and drift; neither answers *"is the expensive one also the unapproved one"*,
and that is the question that changes what somebody does next. The overview's agent table
puts both in one row.

Migration `0008` adds `agent_runs`, partitioned by month like `evidence_events`, and
`tool_usage_daily`. Ingest is `POST /v1/operations/runs`: the same report is sent when a
run starts and again when it ends, `run_id` is chosen by the client, and everything is
replay-safe because collector delivery is at-least-once. A terminal run is immutable by
trigger, so a replayed close is a no-op rather than an error — the upsert is guarded by
`WHERE outcome = 'running'` precisely so one duplicate delivery cannot fail the batch it
arrived in.

**Q-016 is closed, and it was as bad as it read.** The transaction committed in
dependency teardown, which on FastAPI 0.141 runs *after* the response has been handed to
Starlette — so a client that created something and read it straight back raced the commit
and saw a 404 about half the time. `TransactionalRoute` commits at the innermost point
still guaranteed to precede the response (D-037). It also closes a quieter bug: a commit
that failed in teardown failed after a 201 had already gone out, telling the client a row
existed that never did.

**Two tests were silently checking almost nothing.** FastAPI 0.141 changed
`include_router` so `app.routes` is no longer a flat list of `APIRoute` — the auth
invariant, which filters for that type, went from covering 47 endpoints to covering one
**and still passed**. That is the exact failure an enumeration-style test exists to
prevent, so route walking is now a shared helper that imports the private names
deliberately, and `tests/unit/test_routes.py` asserts the walk is plausible rather than
merely non-empty (D-038). Separately the whole unit suite had been erroring out on a
deprecated `pytest-asyncio` fixture in `conftest.py`; 478 unit tests now run.

**The tool reconciliation was crying wolf.** Descriptors declare an MCP server as a URL
(`https://mcp.northwind.internal/stripe`) while a runtime reports what the server calls
itself (`stripe`), so exact matching marked 14 of 17 servers undeclared — all false
alarms, which is worse than not checking, because it teaches people to ignore the column.
Declarations are now normalised to several keys and the check is asked *per calling
agent* (D-039). What is left flagged is genuinely undeclared.

**One number on the old dashboard was nonsense.** `slo_attainment_pct` averaged raw
measurement values across service levels in different units — milliseconds and
percentages in the same mean — and reported 1173.1%. It is now the share of service
levels meeting their target, which is unit-free and bounded, and named for what it counts
(D-040).

**The console.** Dark navigation rail, a top bar with search and one shared time window
for every operational screen (D-041), and four new screens: Overview, Runs, Usage & cost,
Tools & MCP, plus an Activity tab on each agent. Charts are hand-drawn SVG rather than a
charting dependency — four primitives, about 400 lines, against roughly 150 kB for the
smallest library that would do the same job.

**Not done, and it is the thing standing between this and your own agents.** The ingest
path has no machine credential. `POST /v1/operations/runs` is the first endpoint an agent
calls *for itself* rather than a human calling on its behalf, and a LangGraph agent using
the Cursor SDK has nothing it can present — so today the only writer is the seed, calling
the service layer in-process. Q-019 records this with its concrete consumer; it is Q-012
wearing a deadline. `home` also has no tests of its own, which is how D-040 reached a
screen.

---



## Previous position — session 8

**Multi-tenant SaaS is no longer forgeable.** Q-004 is closed. The organisation now comes
from a verified OIDC bearer token rather than an `X-Org-Id` header, and `app/auth/` is
three small modules — `jwks` fetches and caches the provider's keys, `tokens` verifies a
token into a `Principal`, `orgs` maps its claims to an organisation through the new
`identity_bindings` table. Generic OIDC rather than a named provider, so Entra, Okta,
Keycloak and Auth0 are configuration (D-034).

The mapping deliberately lives on our side of the boundary. The obvious design reads an
`org_id` claim, which only works when we own the identity provider; an enterprise
authenticating against their own Entra tenant will not add a claim for us, and asking is
how a two-week pilot becomes a two-quarter one. So they give us an issuer and a tenant
id, and we bind it.

Writing the API-level test found two endpoints that had no authentication dependency at
all: `/v1/materiality/-/rules/{id}`, which served the rule set to anyone who could reach
the port while its sibling list endpoint required an organisation, and `/v1/deployment`,
which reported the licensee name and exact version. Both now require a caller. The test
enumerates routes from the app rather than from a hand-kept list, precisely because a
hand-kept list passes while a router added next month sits unguarded — and it asserts the
inverse too, so a new open endpoint cannot be waved through by adding it to the
exemption set.

**Q-011 is closed and the demo path works.** `0002` is back to its shipped three-rung
cross-border constraint and `0006` widens it, which is the only arrangement where a fresh
database and one already past `0002` converge. Verified both ways: `0001`→`0007` applies
to an empty database, and the existing dev database moved `0005`→`0007` in place.

The seed then failed on a different and more interesting constraint. Re-raising a finding
whose fingerprint already exists only bumped `last_seen_at`, so a vulnerability marked
`fixed` that the pipeline found again stayed `fixed` — the recurrence was invisible. And
`triage_finding` set the state without clearing `resolved_at`, so triaging anything
already closed violated `findings_resolution_consistent` and returned a 500 from the
database rather than a validation error. Both were reachable from the API, not just from
the seed; `resolve_finding` had always cleared those fields when moving the other way, so
this was the missing half of a pair. Fixed under D-032.

Two latent breaks fixed on the way. Five routers used Starlette's deprecated
`HTTP_422_UNPROCESSABLE_ENTITY`, which raises a `DeprecationWarning` today and disappears
in a future release, taking app import with it. And the collector's host port was pinned
to 4318, which a host restart moved inside a Windows Hyper-V reserved block — the
container then fails to start with a bind error while nothing holds the port. Both host
ports are now overridable, 4318 still the default.

**The RLS backstop is not one.** Writing `0007` surfaced it: `tests/sql/invariants.sql`
requires every org-scoped table to have row-level security, so the new table got it —
and then the role check showed why that matters less than it should. The application
connects as `aap`, which is `rolsuper` and `rolbypassrls`, so all 40 policies are skipped
at runtime. Explicit `org_id` filtering is doing the whole job. Raised as Q-015 rather
than fixed, because a non-superuser runtime role touches the schema migration, Compose,
the Helm chart and the BYOC install docs.

**What auth does not yet include.** The console still reaches the API through
`AAP_DEV_AUTH_BYPASS`, which `Settings` refuses outside `AAP_ENVIRONMENT=development`, so
local work is unchanged and no deployed environment can use it. A browser login flow is
the next slice (Q-013). There is no way to create an identity binding except SQL, which
is the same gap as organisation provisioning (Q-009). Authorisation beyond tenant scoping
does not exist — every authenticated caller can do everything their organisation can
(Q-014). And the collector posts to `/v1/collect/events` with a bearer API key; that
endpoint does not exist, and machine identity is a different problem from user identity
(Q-012).

---



## Earlier position — session 7

**The schema has met a real Postgres.** All five migrations apply to PostgreSQL 16.15,
the full stack runs in Docker with every service healthy, and an end-to-end dry run
walks the product's core claim — register, accredit, gate, record, seal, prove — in 30
asserted steps against live infrastructure.

That was the largest unknown in the project and it was hiding ten real defects. Three of
them made the product unusable as shipped, and none were reachable from the unit suite:

1. **Sealing was broken.** `anchor_events` built its VALUES list as `:id_0::uuid`, and
  SQLAlchemy's `text()` leaves a bind parameter alone when a colon follows it, so the
   statement reached Postgres with nothing bound and failed on a syntax error. The
   evidence chain — the feature the trust portal exists to serve — could never have
   sealed a batch. The same pattern was latent in the graph reconciliation query.
2. **The API could not boot under Compose.** `AAP_CORS_ORIGINS` is a comma-separated
  list, and pydantic-settings JSON-decodes list fields before validation, so the
   documented environment variable raised `SettingsError` at import. The unit test
   passed the value as an init kwarg, which skips the environment source entirely.
3. **Migrations could not run in the container.** `alembic/env.py` rewrote
  `postgresql+psycopg` to bare `postgresql`, which SQLAlchemy resolves to psycopg2 — a
   library this project does not depend on. It worked on a developer machine that
   happened to have psycopg2 installed.

The fourth deserves its own paragraph, because it is the kind that costs a week.
`Settings.database_url` declares `validation_alias="DATABASE_URL"`, and pydantic-settings
does not apply `env_prefix` to a field that has one — so `AAP_DATABASE_URL` was read by
nothing. The field has a default, so setting the wrong name did not fail; it quietly
pointed at `localhost:5432`. The integration fixture set that name, which meant it
migrated whatever happened to be listening locally instead of its own test container,
and because that was an already-migrated database the upgrade was a silent no-op
indistinguishable from success. **The 16 integration tests reported green for a session
without having applied a single migration.** They now run against a genuinely fresh
database and still pass, the field accepts both names, and the fixture asserts it
reached head on the URL it was handed.

The fifth is the same failure wearing different clothes. The console container never set
`VITE_API_MODE`, whose default is `mock`, so a stack with every service healthy served
fixtures from `src/mocks` and opened no socket at all. That is worse than an outage: the
fixture data looks like a working product, so there is nothing to investigate. It now
builds in `live` mode and proxies `/v1` to the API through its own origin.

The rest were a reserved word used as a column name (`window`), a JSON example in a SQL
comment that SQLAlchemy parsed as bind parameters, an evidence vocabulary that had
drifted between two migrations, `make bootstrap` depending on an `openssl` binary this
machine does not have, and three container defects (two Dockerfiles that installed a
package whose source they had not copied, an nginx `pid` directive in the wrong context,
and an IPv4-only bind that made the container's own health check fail).

**The demo path now exists.** `seed/generate.py` builds a deterministic estate —
client customers with engagements and service levels, a fleet with version histories,
releases verdicted by the real engine, accreditations in three states, a sealed evidence
chain, findings, posture and SLO measurements — entirely through the service layer, so a
seed run is also the broadest exercise of the write path in the project. Windows `.cmd`
scripts in `scripts/` cover start, stop, status, logs, seed, reset, smoke, test and
bootstrap, because `make` needs `sh` and `openssl` and neither is present here. The
console was found to be serving **fixtures** rather than the database: the container
never set `VITE_API_MODE`, so a completely healthy stack showed mock data that looks
exactly like a working product. It is now built live and proxies the API through its own
origin.

**Next slice: blocked on Q-011.** `scripts\aap start` cannot complete a seed against any
existing database, because D-021's four-rung cross-border constraint was applied by
editing migration `0002` after it had already run. Needs a decision before the demo path
works end to end. *(Closed session 8.)*

**Not blocked, but hold in mind.** This project is not under version control (Q-010) —
the largest risk on the list, and the cheapest to fix. `saas` tenant resolution still
reads a forgeable header (Q-004). Five domains have token coverage above the repository
layer (Q-008). Organisations have no provisioning path, so the dry run needed a
hand-written `INSERT` (Q-009). *(Q-004 closed session 8; Q-008, Q-009 and Q-010 still
open.)*

---



## Module status

**Session 35 moved nothing to `OK`.** F2 changed `bootstrap` (two navigation manifests,
`product_mode`, capability flags), the `web` shell and the `home` landing page, and added
25 navigation unit tests — but every one of those rows depends on a browser or a database
this machine does not have, so none of them earns `OK` on a passing type-check. `bootstrap`
stays `WIP`, `home` stays `WIP`, `web` contract integrity stays `WIP` and this session
supplied the concrete reason it should: see the `SessionSummary` drift below.

**Session 36 added `agent_runtime` and `agent_actions`, and moved neither to `OK`.** F1 is a
schema slice: two migrations, six thin ORM models and one boundary schema. Both rows are
`WIP` because **written is not applied** — no PostgreSQL was reachable, so the DDL has never
executed and every SQL invariant covering it is unrun. `repository`, `service`, `router` and
`screen` read `—` rather than `WIP` because they are **not missing, they are not this
slice**: the prompt forbids an endpoint and M3 owns ingestion. `agent_actions` earns `OK` on
`schemas` — `aap.action.v1` is complete, and the unit suite proves its vocabularies agree
with the migrations' CHECK constraints without needing a server. `agent_runtime` has no
schema cell to fill: nothing crosses the boundary as a runtime-identity object yet.

`agent_actions` was also added to `DOMAINS_OUTSIDE_LAYER` in `app/domains/layer_order.py`,
beside `security_audit` and for the same reason. It answers "what happened", which every
layer produces and none owns; giving it a position in the dependency chain would force an
ordering between the ledger and the capabilities it records, and there is no honest one.

**Session 34 moved `auth`, added `bootstrap`, and moved `web` contract integrity.** The
`auth` row now covers the console sign-in domain (`app/domains/auth` plus `app/auth`), not
just the old OIDC bearer-token verification. Its `tests` cell is `OK` for what runs without
a database and its `screen` cell is `OK` — but read the `Verification status` section
before trusting either: none of it has been exercised against PostgreSQL.

**Session 33 changed no module state.** It changed prompts, migration documentation and
generated design diagrams only. No schema, service, router, screen or test was implemented.

**Session 32 changed no module state.** The only code touched was a hardcoded employer
domain in three dev-bypass paths (`api/deps`, the web OIDC fallback, and the audit-UI
script), replaced with `localhost`. That is a string fix, not a slice, so no cell moves. The
entities and columns specified by D-066…D-072 are **design only** — nothing below claims
them, and nothing below should be read as claiming them.

Session 28 removed runtime Nexus fixtures, split Activity into live routes, added profile
and member-bound Platform Keys, and connected MCP/model decisions to Observe and audit.
Layer columns are the vertical slice from AGENTS.md.
States: `—` not started · `WIP` in progress · `OK` complete · `CHG` change requested,
must clear before new work.

`OK` in the `tests` column means the module's own logic is covered. `registry`,
`evidence` and `graph` now also have repository tests against a real Postgres; the
others are still covered only above the database.


| Module                                                              | Migration  | schemas | repository | service | router | tests | screen | State |
| ------------------------------------------------------------------- | ---------- | ------- | ---------- | ------- | ------ | ----- | ------ | ----- |
| `config` / providers                                                | n/a        | n/a     | n/a        | OK      | n/a    | OK    | n/a    | OK    |
| `auth` (providers, console sessions, tenant binding)                | 0007, 0022 | OK      | OK         | OK      | OK     | OK    | OK     | WIP   |
| `bootstrap` (one-request identity, navigation manifest)             | n/a        | OK      | n/a        | OK      | OK     | OK    | OK     | WIP   |
| `api/deps` (tenant resolution)                                      | n/a        | n/a     | n/a        | OK      | n/a    | OK    | n/a    | OK    |
| `registry` (agents, versions)                                       | 0001       | OK      | OK         | OK      | OK     | OK    | OK     | OK    |
| `releases` (differ, gate, review brief)                             | 0001, 0011 | OK      | OK         | OK      | OK     | OK    | OK     | WIP   |
| `customers`                                                         | 0002       | OK      | OK         | OK      | OK     | OK    | OK     | OK    |
| `engagements` (+ drift)                                             | 0002       | OK      | OK         | OK      | OK     | OK    | OK     | OK    |
| `frameworks` (controls, mappings)                                   | 0002       | OK      | OK         | OK      | OK     | WIP   | OK     | WIP   |
| `bom`                                                               | 0001       | OK      | OK         | OK      | OK     | WIP   | OK     | WIP   |
| `evidence` (hash chain, Merkle)                                     | 0003       | OK      | OK         | OK      | OK     | OK    | OK     | OK    |
| `graph`                                                             | 0004       | OK      | OK         | OK      | OK     | OK    | OK     | OK    |
| `policy`                                                            | 0005       | OK      | OK         | OK      | OK     | OK    | OK     | OK    |
| `materiality` (rules engine)                                        | 0001       | OK      | OK         | OK      | OK     | OK    | OK     | OK    |
| `accreditation`                                                     | 0005       | OK      | OK         | OK      | OK     | WIP   | OK     | WIP   |
| `attestation`                                                       | 0005       | OK      | OK         | OK      | OK     | WIP   | OK     | WIP   |
| `assurance` (findings, probes, rule gaps)                           | 0005, 0013 | OK      | OK         | OK      | OK     | OK    | OK     | OK    |
| `composition` (tools, rules, skills, subagents)                     | 0010       | OK      | OK         | OK      | OK     | OK    | OK     | OK    |
| `model_routing` (catalogue, residency, Router control plane)        | 0012, 0015, 0016 | OK | OK         | OK      | OK     | OK    | OK     | OK    |
| `workload_identity` (projects, revocable machine credentials)      | 0014, 0018 | OK      | OK         | OK      | OK     | OK    | OK     | OK    |
| `members` (people, IdP bindings, teams)                            | 0017       | OK      | OK         | OK      | OK     | OK    | OK     | OK    |
| `access` (roles, grants, elevation requests)                       | 0017       | OK      | OK         | OK      | OK     | OK    | OK     | OK    |
| `connections` (provider credentials, versions, rotation)           | 0017       | OK      | OK         | OK      | OK     | —     | OK     | WIP   |
| `mcp_registry` (servers, snapshots, capabilities, grants, drift)    | 0017       | OK      | OK         | OK      | OK     | OK    | OK     | OK    |
| `security_audit` (append-only account history)                     | 0017       | OK      | OK         | OK      | OK     | OK    | OK     | OK    |
| `agent_runtime` (instances, agent sessions, tasks, delegations)     | 0023       | —       | —          | —       | —      | WIP   | —      | WIP   |
| `agent_actions` (content-free action ledger, `aap.action.v1`)        | 0024       | OK      | —          | —       | —      | WIP   | —      | WIP   |
| `modules` (licensed suite manifest and capability gates)           | n/a        | OK      | n/a        | OK      | OK     | OK    | OK     | OK    |
| Go `gateway` (OpenAI-compatible Router data plane)                 | n/a        | OK      | n/a        | OK      | OK     | WIP   | OK     | WIP   |
| MCP adapter (authenticated MCP policy/data plane)                  | n/a        | OK      | n/a        | OK      | OK     | OK    | n/a    | OK    |
| Observe (OTLP ingest, execution/user analytics, retention)         | observe 001–006; CH 001–006 | OK | OK | OK | OK | OK | WIP | WIP |
| Prompt (prompt/rule/skill/context workspace and playground)        | prompt 001–003 | OK | OK         | OK      | OK     | OK    | OK     | OK    |
| Evaluate (datasets, experiments, scores, queues, release gates)    | evaluate 001–004 | OK | OK       | OK      | OK     | OK    | OK     | OK    |
| tracing SDKs (Python and TypeScript)                                | n/a        | OK      | n/a        | OK      | n/a    | OK    | n/a    | OK    |
| Agent Execution Observability redesign                             | observe 003–006; CH 001–006 | OK | OK | OK | OK | OK | WIP | WIP |
| `sla`                                                               | 0005       | OK      | OK         | OK      | OK     | WIP   | OK     | WIP   |
| `portal` (customer-facing)                                          | 0005       | OK      | OK         | OK      | OK     | OK    | OK     | OK    |
| `operations` (runs, cost, tools, MCP, tracing)                      | 0009       | OK      | OK         | OK      | OK     | OK    | OK     | OK    |
| `home` (landing page)                                               | n/a        | OK      | n/a        | OK      | OK     | WIP   | OK     | WIP   |
| `aap` CLI                                                           | n/a        | n/a     | n/a        | OK      | n/a    | OK    | n/a    | OK    |
| `seed` (demo estate)                                                | n/a        | n/a     | n/a        | OK      | n/a    | OK    | n/a    | OK    |
| `web` contract integrity (generated types, path check, route sweep) | n/a        | OK      | n/a        | OK      | n/a    | OK    | n/a    | WIP   |


Four session-25 modules are now certified against PostgreSQL 16: members/access, MCP
registry and security audit have 54 passing integration tests in addition to their unit
coverage. First contact found the missing ORM UUID server defaults and async rediscovery
refresh defect that the skipped suite could not expose. `connections` remains `WIP`: its
tables are applied and its live screen builds, but rotation and secret-version behavior
still have no dedicated database integration suite.

Writing the unit tests did find one real bug, which is recorded as D-057: the audit
`category` vocabulary had drifted between the Pydantic enum and the CHECK constraint in
`0017`, so four of the seven categories — including `mcp`, the one the registry emits most
— would have been rejected at INSERT. It would have failed only for the events carrying
those categories, meaning the trail would have looked healthy while one subsystem's history
silently never landed. Nothing else in the suite could have seen it, because the schema and
the migration are the only two places the list is written and neither imports the other.

`web` contract integrity is `WIP` rather than `OK` and the reason is the whole point of it:
`check:api` proves a path exists in `openapi.json` and `Wire<>` proves a type matches
`openapi.json`, but **nothing proves** `openapi.json` **is current.** It is a checked-in
snapshot. The first backend change not followed by `npm run client` returns this to
decorative, and the failure mode is the one it was built to prevent — everything passes,
nothing works. It becomes `OK` when CI regenerates the spec from a running API and fails on
a diff. Until then the guarantee is conditional and should be described that way.

**Session 35 hit that failure for real, which moves this from a predicted risk to an
observed one.** F0 added a second `SessionSummary` in the auth domain. FastAPI resolves a
name collision by fully qualifying both, so the schema the console had always known as
`SessionSummary` stopped existing under that name — and `Wire<"SessionSummary">` kept
compiling, because the stale snapshot still contained the old name. Regenerating the spec
turned it into a compile error immediately; without regenerating, nothing anywhere would
have reported a problem. Note what this says about the gap: the drift was introduced by
one session and found by an unrelated one, two sessions later, by accident.

The screens that had been calling dead URLs — Findings, Evidence, Policy, Service levels,
Attestations, the BOM tab, blast radius, release impact — now call routes that exist and
read fields the API returns. That is a floor, not a design: their `screen` column stays
`OK` on the strength of working, and `tasks.md` §5 carries the redesign they still need.

`operations` is `OK` on every layer including tests: 21 unit tests on the logic that has
no database in it, and 14 against real Postgres covering the partition, the immutability
trigger, the replay-safe upsert, `percentile_cont` skipping in-flight runs, the
declaration heuristic and tenant scoping. It is the first module written with its tests
in the same session rather than after, which is why it did not land as `WIP`.

`home` stays `WIP`. It grew substantially this session — it now composes `operations`,
`registry`, `assurance`, `accreditation`, `engagements` and `sla` into one payload — and
its own composition logic has no tests. The `_estate_attainment` bug (D-040) shipped and
was only caught by reading the rendered number, which is exactly what a test would have
caught first.

`auth` and `api/deps` are `OK` for the server side of authentication and tenant
resolution: a token is verified, its claims are bound to an organisation, and 133 tests
drive the result through the real ASGI app. Their `screen` column is `—` because there is
no browser login flow yet (Q-013), and the console reaches the API through the
development bypass. That bypass cannot be enabled outside `AAP_ENVIRONMENT=development`,
so it is a local-work convenience rather than a deployed weakness — but multi-tenant SaaS
is not demonstrable to an outside audience until the console can sign a user in.

The remaining `WIP` modules are `WIP` on test coverage alone; all four layers are written
and type-clean. What is left is thin: `bom` (1 test), `attestation` (3), `frameworks` (4),
`sla` (5). `registry`, `evidence` and `graph` moved to `OK` because they now have
repository tests against a real database, which is a different and stronger claim than
the unit suite. `assurance` stays `WIP` despite gaining the findings-lifecycle tests this
session: they cover the state machine that was broken, not probes or posture.

`portal` moved to `OK` and was the right one to take first. It is the only surface a
customer's own staff reach, and two clients of the same consultancy share an `org_id` —
so row-level security and the `org_id` filter, which carry isolation everywhere else,
do nothing here. The boundary is `engagement_id` alone. It went from 1 test to 15: seven
unit tests on the pure scoping filter, and eight against real Postgres covering the view,
an engagement slug resolved from the wrong tenant, an agent whose scope was withdrawn,
and a pack id from another engagement requested through this one's slug. That last one is
the direct-object reference an external tester would try first. All of them pass, so this
is coverage of behaviour that was already correct rather than a bug found — but it was
correct without anything holding it that way.

### Verification status

Rows name their session where useful; the newest Session 25 rows are the account/access
implementation, and the Session 20 rows remain the current Agent Execution Observability
verification.


| Check                                                                  | Result                                                                                                                                                         |
| ---------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Identity/MCP repair (session 29)                                      | Four formerly-403 endpoints return 200 without a tenant header; profile resolves; **21/21** member/access PostgreSQL tests pass; ESLint, contract checks, TypeScript and production build pass; MCP adapter healthy with 38 approved tools |
| Nexus console slice (session 26)                                       | ESLint, TypeScript, production build and 137-path API contract check pass; deployed web/API/PostgreSQL healthy on `:5173`/`:8000`/`:5432`                     |
| `0017` integration certification (session 26)                           | **54 passed** against disposable PostgreSQL 16 after fixing 14 UUID server defaults and unchanged-snapshot ORM refresh                                          |
| API quality after first-contact fixes (session 26)                      | focused Ruff clean; strict `mypy app` clean across **195 source files**                                                                                         |
| API quality suite (session 25)                                         | `ruff check` and `ruff format --check` clean; strict `mypy app seed` clean, **199 source files**                                                                 |
| `pytest tests` (API, session 25)                                       | **879 passed, 165 skipped** in 9m44s. Every skip is an integration test with no Postgres to run against                                                          |
| New unit tests (session 25)                                            | **72 passed** — 12 keyset pagination, 18 authorization, 20 MCP capability digest, 22 audit record and schema/migration agreement                                 |
| New integration tests (session 25)                                     | **54 collected, 54 skipped — none executed.** No PostgreSQL on this machine, so the append-only triggers, drift detection and keyset walk are unverified          |
| `tests/sql/invariants.sql` (session 25)                                | extended from 8 to 14 sections for `0017`. **Not executed** — needs `psql`, which is not installed here                                                          |
| `0017_account_access_registry` (session 25)                            | **written, not applied.** `alembic heads` confirms one linear head; the DDL itself has never reached a server                                                    |
| Console build (session 25)                                             | `tsc --noEmit`, `eslint --max-warnings 0` and `vite build` clean; seven new admin screens code-split, largest 15.9 kB (4.1 kB gzip)                              |
| Local runtime (session 25)                                             | **none.** Docker Desktop absent, no Postgres service, no `psql`. Nothing in this session was exercised against a running stack                                   |
| Observe quality suite (session 20)                                     | ruff and format clean, strict mypy clean (44 source files), **51 unit + 2 integration tests passed, 1 real-services test skipped**                               |
| Collector quality suite (session 20)                                   | ruff and format clean after one import-order repair, strict mypy clean, **36 tests passed**                                                                     |
| Tracing SDKs (session 20)                                              | Python ruff/format/mypy clean and **33 tests passed**; TypeScript typecheck/lint clean and **29 tests passed**                                                   |
| Execution console build (session 20)                                  | runtime/API contract checks pass; **101 request paths resolve against 236 routes**; TypeScript and Vite production build plus ESLint clean                       |
| Observe migrations and FOSS demo (session 20)                         | PostgreSQL Observe 001–006 and ClickHouse 001–006 applied; containerized deterministic demo reached the collector and query API as `foss-08f0dd0a794c5d5296c9340e` |
| Runtime suite status (session 20)                                     | API, web, gateway, collector, Observe ×3, Prompt, Evaluate ×2, PostgreSQL, Redis and ClickHouse running; configured health checks healthy                        |
| Runtime suite Compose deployment (session 18)                          | API/web/gateway/collector/Observe ×3/Prompt/Evaluate ×2/PostgreSQL/Redis/ClickHouse running; every configured health check passes; migrations/seed exited 0      |
| OTLP live path (session 18)                                            | standard OTLP/JSON hex IDs accepted; authenticated collector → Observe → ClickHouse → API BFF, manifest `done` on first attempt and query total 1                |
| Go Router certification (session 18)                                   | `gofmt`, `go vet ./...`, `go test -race ./...` clean                                                                                                           |
| Runtime console build (session 18)                                     | 91 request paths resolve against 220 OpenAPI routes; TypeScript and Vite production build clean                                                                |
| Focused runtime API tests (session 18)                                 | 336 passed, 1 skipped; the one isolation-test harness failure was fixed and its focused rerun passed                                                           |
| Observe and collector lint (session 18)                                | `ruff check` and `ruff format --check` clean from each package root                                                                                            |
| `pytest tests` (API)                                                   | **581 passed, 4 skipped** — includes `test_model_drift`                                                                                                        |
| `pytest tests/unit`                                                    | 478 passed. Was 331 *errors* before this session: a deprecated `pytest-asyncio` fixture in `conftest.py`, promoted to an error by the project's warning config |
| `pytest tests/unit/test_operations.py`                                 | 21 passed — bucket merging, duration, report validation, declaration keys, window arithmetic                                                                   |
| `pytest tests/integration/test_operations.py`                          | 14 passed against real Postgres                                                                                                                                |
| `tsc --noEmit`, `eslint --max-warnings 0`, `vite build` (web, s13 fix) | **clean** — main 414 kB (121 kB gzip); Cytoscape 444 kB async                                                                                                  |
| `tsc --noEmit`, `eslint --max-warnings 0`, `vite build` (web, s10 UI)  | clean — main chunk 862 kB (266 kB gzip); graph still lazy                                                                                                      |
| `tsc --noEmit`, `eslint --max-warnings 0`, `vite build` (web, s9)      | clean; 397 kB main (117 kB gzip), graph split at 453 kB                                                                                                        |
| Console, live                                                          | Overview, Runs, Usage & cost, Tools & MCP and the agent Activity tab render against the seeded estate                                                          |
| Operations endpoints, live                                             | all nine return 200; `/v1/home/summary` is 30 kB at 90 days and 312 ms warm                                                                                    |
| `mypy app seed` (strict)                                               | clean, 121 files                                                                                                                                               |
| `ruff check` + `ruff format --check`                                   | clean, 172 files                                                                                                                                               |
| `pytest` (`aap-cli`)                                                   | 31 passed *(s8)*                                                                                                                                               |
| Auth suite                                                             | 133 API-level + 29 token/key + 12 org-binding tests; every `/v1` GET enumerated from the app returns 401 without a credential                                  |
| `portal` coverage                                                      | 1 test → 15. Cross-engagement isolation holds for the view, the slug lookup, withdrawn scope and pack downloads                                                |
| `tests/sql/invariants.sql`                                             | 18 invariants hold, including the RLS backstop it had just started failing                                                                                     |
| `alembic upgrade head` on PostgreSQL 16.15                             | **all eight applied**, on the existing database and from empty                                                                                                 |
| `alembic heads` / `current`                                            | linear, single head, database at `0013_probe_assertions`                                                                                                       |
| `pytest tests` (API, session 14)                                       | **653 passed, 4 skipped**                                                                                                                                      |
| `python -m tests.smoke` (session 14)                                   | 30 checks, after an API restart to prove no import cycle at startup                                                                                            |
| `tsc` / `eslint --max-warnings 0` / `vite build` (session 14)          | clean — main 437 kB (127 kB gzip), Cytoscape 444 kB async                                                                                                      |
| New endpoints, live                                                    | all nine return populated payloads against the seeded estate; paths verified from `openapi.json` rather than assumed                                           |
| `0009_run_steps` downgrade → upgrade                                   | clean both ways (verified session 11)                                                                                                                          |
| Tracing endpoints, live                                                | `GET .../runs/{id}` and `GET .../agents/{id}/graph` 200 against seeded org                                                                                     |
| `python -m tests.smoke`                                                | **30 checks × 3 consecutive runs** — placeholder org auto-resolved to seeded `default` tenant                                                                  |
| `alembic downgrade 0006` then `upgrade head`                           | clean both ways — `0007` is reversible *(s8)*                                                                                                                  |
| Docker stack                                                           | all five healthy — `postgres`, `api`, `worker`, `web`, `collector`; `migrate` exits 0                                                                          |
| Console proxy                                                          | `/v1/agents` returns live rows through the console's own origin on `:5173`                                                                                     |
| Seed generator                                                         | builds the demo estate on a fresh database; 5 tests assert the result                                                                                          |
| `pytest` with no database reachable                                    | integration degrades cleanly *(s7)*                                                                                                                            |
| `pytest -W error::UserWarning`                                         | clean with a hostile `AAP_*` environment set *(s7)*                                                                                                            |
| `mypy aap_cli` (strict)                                                | clean, 13 files *(s7)*                                                                                                                                         |
| `aap` end-to-end on `examples/claims-triage`                           | validate 0, diff 12 changes, gate blocks with exit 2 *(s7)*                                                                                                    |


The smoke run is the one to point at in a demo. It registers an agent, publishes an
accredited baseline, has an immaterial change allowed and a material one refused with
the rule IDs named, records evidence, seals a Merkle batch, and then recomputes the
published root from the inclusion proof independently — the calculation an external
auditor would reimplement — and confirms a tampered digest fails it.

Q-005 is closed: the 45 mypy errors in `providers/` and `licensing.py` were fixed by
narrowing key types to `EllipticCurvePrivateKey` / `EllipticCurvePublicKey` with
`isinstance` guards and casting at the untyped-SDK boundary, not by relaxing strict mode.
The narrowing found a real bug on the way: `providers/secrets.py` had `return` statements
indented inside `except` blocks, so both the AWS Secrets Manager and Vault paths returned
`None` on success.

---



## Migrations

**Session 36 wrote `0023` and `0024`.** Both are hand-written per AGENTS.md rule 7,
reversible, and chain linearly off `0022`. `alembic heads` reports exactly one head,
`0024_agent_actions_ledger`, and `tests/unit/test_agent_actions.py` asserts it so two
parallel sessions cannot produce sibling heads without a test saying so.

**Neither has been applied, and that is the word that matters.** `0019`–`0024` are all
**written and unapplied**: this machine has no Docker, no PostgreSQL and no `psql`, so
`alembic upgrade head` has never run against any of them and neither has
`tests/sql/invariants.sql`. Reviewing DDL line by line is not the same as executing it, and
every previous session that met a real server found something — see the first-contact table
below.

**One correction to an earlier migration's omission.** `0023` adds
`UNIQUE (org_id, id)` to `agents` and `agent_versions`. Both were absent from every
migration although `app/db/models/registry.py` has declared one on `agents` since `0001`,
which the drift test could not catch because it compares columns and not constraints. Every
composite tenant-safe foreign key in `0023` references them, so this is a prerequisite
rather than tidying. Guarded by `pg_constraint` lookups, because `ADD CONSTRAINT` has no
`IF NOT EXISTS`, and deliberately not dropped on downgrade: they are true of any database
that ever reached this revision.

**Session 35 added no migration.** F2 is UI structure and a bootstrap response shape; no
table, column or constraint changed.

**Sessions 32–33 added no migration.** The research pass and prompt regeneration specified
the next executable revisions as `0023_agent_runtime_identity` and
`0024_agent_actions_ledger`; session 36 wrote them. Application status of `0019`–`0022` was
not re-verified in session 33, so the table says **written, application unverified** rather
than guessing.

Session 32 specified new entities but wrote no
revision, and the distinction matters: `agent_versions`, `agent_instances`, `sessions`,
`tasks`, `delegations`, `capability_sources`, `capabilities`, `capability_grants`,
`credential_bindings`, `credential_leases` and the mandatory `enforcement_grade` column
(D-066, D-069, D-071, D-072) are **specified, not written, and certainly not applied**. They
live in `design/03-data-model.md`, `design/14` §3 and `design/15` §4/§6. The renames in D-066
are an expand→backfill→dual-read→contract sequence when someone writes them, not an
`ALTER TABLE ... RENAME`.

| Revision                    | Covers                                                                                                                                                                               | Status                                                           |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------- |
| `0001_baseline`             | organizations, agents, agent_versions, agent_ownership, bom_components, releases, release_changes, jobs                                                                              | **applied** to PostgreSQL 16.15                                  |
| `0002_company_model`        | customers, customer_contacts, engagements, engagement_service_levels, engagement_agents, frameworks, framework_controls, control_mappings, customer_frameworks                       | **applied** — fixed on first contact                             |
| `0003_evidence`             | evidence_events (partitioned), merkle_batches, published checkpoints                                                                                                                 | **applied** — partitioning and triggers verified working         |
| `0004_graph`                | graph_nodes, graph_edges, discovery_sources, discovery_findings                                                                                                                      | **applied**                                                      |
| `0005_assurance`            | policy_rules, findings, probe_suites, posture, accreditations, accreditation_packs, control_answers, slos                                                                            | **applied** — fixed on first contact                             |
| `0006_cross_border_consent` | widens `engagements_cross_border_valid` to the four rungs of D-021                                                                                                                   | **applied** — closes Q-011                                       |
| `0007_identity_bindings`    | `identity_bindings`: verified OIDC claims mapped to organisations                                                                                                                    | **applied** — under forced RLS like every other org-scoped table |
| `0008_operations`           | `agent_runs` (partitioned by month), `tool_usage_daily`, the `run_outcome` and `tool_surface` enums, an immutability trigger on terminal runs and the partition-maintenance function | **applied**                                                      |
| `0009_run_steps`            | `run_steps` (partitioned by month), `step_kind`, terminal-step immutability, `ensure_run_step_partition`                                                                             | **applied**                                                      |


| `0010_agent_composition` | `composition_rule_obligations` (512-byte CHECK), `composition_reconciliations`, extended `component_kind` | **applied**, reversible |
| `0011_change_review` | `releases.reviewed_descriptor_digest`, composition change categories, `renamed` change kind | **applied**, reversible |
| `0012_model_routing` | `model_catalog_entries` — global reference rows plus tenant overrides under RLS — and classification state | **applied**, reversible |
| `0013_probe_assertions` | `probe_suites.content_digest`, `probe_runs.summary_json`, `control_mappings.obligation_template_id`, `obligation_templates`, two new probe suites | **applied**, reversible |
| `0014_workload_identity` | projects, scoped/revocable workload credentials and generations under RLS | **applied** to local PostgreSQL 16 |
| `0015_router_runtime` | deployments, routes, targets and immutable signed router snapshots | **applied** to local PostgreSQL 16 |
| `0016_router_runtime_hardening` | capture policy, credential limits, signing-key registry, config digest and route identity constraints | **applied** to local PostgreSQL 16 |
| `0017_account_access_registry` | members, member_identities, teams, team_members, roles (+8 seeded built-ins), access_grants, access_requests, provider_connections, connection_secret_versions, connection_grants, mcp_servers, mcp_snapshots, mcp_capabilities, mcp_grants, mcp_capability_usage_daily, security_audit_events (partitioned by month) | **applied** to local PostgreSQL 16; 54 integration tests pass |
| `0018_workload_member_binding` | optional account-scoped `member_id` binding on workload credentials for attributable model/MCP access | **applied** to local PostgreSQL 16; workload identity integration suite passes (11/11) |
| `0019_account_owner_role` | account-owner role and grant semantics | **written; application status not re-verified in session 33** |
| `0020_backfill_account_owner` | account-owner backfill | **written; application status not re-verified in session 33** |
| `0021_ensure_account_owner` | enforce account-owner presence | **written; application status not re-verified in session 33** |
| `0022_auth_sessions_and_providers` | `auth_providers`, `auth_sessions` and RLS | **written; not applied.** Session 34 implemented against it and exported ORM models (`app/db/models/auth.py`), but no PostgreSQL and no container runtime were available on this machine, so it has never been run. `tests/integration/test_auth_sessions.py` asserts RLS, forced RLS and zero model/migration drift on both tables — **written, never executed**. No second auth migration was created; inspection found no missing field. |
| `0023_agent_runtime_identity` | `agent_instances`, `agent_sessions`, `agent_tasks`, `delegations`, all under forced RLS; `enforce_session_taint_monotonic()` and `enforce_delegation_attenuation()`; and the `UNIQUE (org_id, id)` on `agents` and `agent_versions` that was missing from every migration although the ORM has declared it since `0001` — every composite tenant-safe FK here needs it | **written, not applied** (session 36). Hand-written and reversible; `down_revision` is `0022`, so the chain stays linear. No PostgreSQL on this machine, so the DDL has never reached a server |
| `0024_agent_actions_ledger` | `agent_actions` partitioned monthly by `occurred_at`, append-only by trigger, RLS on the parent and on every partition; `agent_action_receipts` as the unpartitioned idempotency registry; `agent_action_facets_valid()`, `effective_enforcement_grade()`, `forbid_agent_ledger_mutation()` and `ensure_agent_action_partition()` | **written, not applied** (session 36). Current head; `alembic heads` reports exactly one, asserted by `tests/unit/test_agent_actions.py`. Sections 15–23 of `tests/sql/invariants.sql` cover it and **have never executed** |
| Observe `001_initial`–`006_security_retention_rls` | manifests; execution/session/user metadata; actors/links; payload audit; projection outbox; sampling; retention/legal hold; RLS | **applied** to the current service-owned `observe` PostgreSQL database |
| Observe ClickHouse `001_execution_observability`–`006_framework` | typed execution observations/events/edges, SDK/user dimensions, sampling, MCP/A2A correlation and framework identity | **applied** to the current `observe` ClickHouse database |
| Prompt `001_initial`–`003_playground_cancel_requested` | artifacts/revisions/labels/audit and durable playground cancellation | **applied** to service-owned `prompt` database |
| Evaluate `001_initial`–`004_alert_ack` | datasets, experiments, evaluators, scores, online rules, annotation, release gates and alerts | **applied** to service-owned `evaluate` database |

Observe PostgreSQL revisions 003–006 and ClickHouse revisions 001–006 were written and
applied in session 20. They have not yet been re-certified from an empty volume; that is
part of the remaining Phase 13 gate.

Session 21 added no migration. A gateway snapshot revision 2 and any durable A2A task
ledger are proposals only and must not receive revision IDs until Q-023 is resolved.
Session 22 recorded the account/access/connection/MCP-registry/audit tables as unnumbered
proposals. Sessions 23–24 added no migrations; pricing, UI and HLD artifacts do not change
a runtime or persistence contract.

Session 25 wrote `0017_account_access_registry`. Session 26 applied it to PostgreSQL 16 and
ran the 54 account/access/MCP/audit integration tests against a disposable `aap_test`
database. First execution exposed ORM server-default and MCP rediscovery refresh defects;
both were fixed before the suite reached 54/54 passing.

All seventeen Alembic revisions are applied. The chain is linear with a single head at
`0017_account_access_registry`; service-owned migration ledgers are also current.

The last four were written by four agents working in parallel. Each was given a pre-assigned
revision id and told to re-point `down_revision` at the actual head immediately before
applying. That is the only reason the chain stayed linear rather than growing four sibling
heads, and it is worth remembering the next time work is parallelised: Alembic's chain is a
shared mutable resource and nothing in the tooling defends it.

`0008` follows `0003`'s partitioning pattern because runs have the same shape as evidence
— high volume, written once, read by window, and never updated after they finish. The
immutability trigger is narrower than evidence's: a run is mutable while `outcome = 'running'` and frozen the moment it is not, which is what lets one report open it and a
second close it while still refusing a third.

`tool_usage_daily` is a rollup rather than a row per call, because a tool call is the
highest-cardinality event in the system by an order of magnitude and nothing on any
screen asks about an individual one. The unique constraint is
`(org_id, agent_id, day, surface, server_name, tool_name)`, which is also the upsert's
conflict target.

`0006` exists because `0002` was edited after it had already run (Q-011). `0002` has been
restored to its shipped three-rung constraint and `0006` widens it, which is the only
arrangement where a fresh database and one already past `0002` end up with the same
schema. The rule this cost a session to learn: **an applied migration is immutable, and
"it is only my dev database" is how you find out it was not.**

That rule was then nearly broken again within the hour. `0007` shipped without row-level
security, on the reasoning that a table read *to determine* the tenant has nothing to
scope by. `tests/sql/invariants.sql` rejected it, correctly — `current_org_matches` has an
explicit bypass that `admin_session` sets, so the policy and the pre-tenant lookup
coexist fine. Because `0007` had already been applied here, the fix was to downgrade
through it and re-apply rather than edit in place, which also demonstrated its downgrade.

`0003` was the one flagged as most likely to fail first contact. It did not — the
declarative partitioning and the immutability triggers worked as written, and rows route
to `evidence_events_YYYYMM` rather than the parent or the catch-all. The failures came
from elsewhere:


| Revision | What broke on first contact                                                            | Fix                                                                                             |
| -------- | -------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| `0002`   | `window` as a column name — reserved in Postgres                                       | renamed to `measurement_window` end to end, including the API and the console (D-018)           |
| `0005`   | a JSON example in a SQL comment: `op.execute` parsed `:99` and `:5` as bind parameters | spaced the colons; the pattern is now documented in the migration (D-019)                       |
| `0005`   | seeded control mappings for evidence kinds a `0002` CHECK constraint did not allow     | `0003` converts the column to the canonical `evidence_kind` enum, so the two cannot drift again |


One migration property worth recording because it was demonstrated rather than assumed:
when `0002` failed mid-way, Alembic rolled it back atomically and left the database at
`0001_baseline` with none of `0002`'s tables present. `transaction_per_migration` works.

---



## Decisions

Recorded so they are not re-litigated. Full reasoning for the larger ones lives in
`docs/adr/`.


| ID    | Decision                                                                                                                                                                                | Rationale                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        | ADR    |
| ----- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------ |
| D-001 | Python for the control plane; Go later for collector and ingest only                                                                                                                    | 278 rps peak leaves 10-30x headroom; Go is justified by security-review surface, not speed                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       | —      |
| D-002 | One FastAPI service, one Postgres. No microservices, no broker                                                                                                                          | Organisational tool, not a performance one. Team of one                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | —      |
| D-003 | Three deployment modes: `saas`, `byoc`, `airgap`                                                                                                                                        | Regulated buyers will not send evidence to a vendor cloud                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        | —      |
| D-004 | Control-plane availability target 99.9%, not five nines                                                                                                                                 | Aurora Multi-AZ SLA is 99.99%; composite stack is ~99.93%. Sell zero evidence loss instead                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       | —      |
| D-005 | Graph via recursive CTEs, escape hatch is an in-memory graph                                                                                                                            | Apache AGE is unavailable on managed Postgres, so it fails in BYOC                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               | —      |
| D-006 | Two-level company model: `organizations` own `customers`                                                                                                                                | Accreditation is always produced *for a client*. Without this the product cannot express its own value                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           | `0002` |
| D-007 | Evidence chain uses Merkle batch anchors, not per-event chaining                                                                                                                        | Per-event chaining serialises writes and makes verification O(n); RFC 9162 pattern gives O(log n) proofs                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         | —      |
| D-008 | React web app for console and portal, plus an `aap` CLI. No desktop app                                                                                                                 | External auditors will not install vendor software; BYOC would need per-customer signed binaries                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 | `0001` |
| D-009 | Frameworks and control mappings are reference data with nullable `org_id`                                                                                                               | `NULL` means shipped by us; tenant rows are customer questionnaires                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              | `0002` |
| D-010 | `TCH` removed from the ruff rule set                                                                                                                                                    | It optimises import time, which is irrelevant in a long-lived process, and fights Pydantic, FastAPI and SQLAlchemy, all of which resolve annotations at runtime                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  | —      |
| D-011 | ORM models live in `app/db/models/`, not in domain modules                                                                                                                              | The four-file domain rule has no room, and models are read across domains while services stay private                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            | —      |
| D-012 | Domain exceptions carry an `Error` suffix                                                                                                                                               | The project already selected ruff's `N` rules; arguing with the linter costs more than the rename                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                | —      |
| D-013 | The CI gate and the console share one materiality engine; the severity heuristic survives only as a caught-exception fallback                                                           | A gate that disagrees with the system of record about the same descriptor pair destroys trust in both. Pinned by `test_gate_verdict_matches_a_direct_engine_assessment`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | —      |
| D-014 | No `collection` domain. Layer 2 is `services/collector/`; the API side of ingest is `evidence.service.record_events`                                                                    | The module would have been a re-export: adapter registration and reconciliation already live in `graph` as `discovery_sources` / `discovery_findings`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            | —      |
| D-015 | CLI output degrades characters the console cannot encode; it never raises                                                                                                               | A cp1252 Windows runner turned every verdict into a UnicodeEncodeError traceback. A gate that looks broken gets deleted from the pipeline whatever its verdict was                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               | —      |
| D-016 | Global CLI flags are accepted before or after the subcommand                                                                                                                            | `aap preview a b --json` is what people type, and argparse rejects it by default. Subparser copies use `SUPPRESS` so they cannot overwrite a value given earlier                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 | —      |
| D-017 | DML row counts come from `RETURNING <id>` and `len(result.all())`, never `rowcount`                                                                                                     | `session.execute` returns `Result`, which has no `rowcount` under strict typing; `RETURNING` was already the convention elsewhere in the codebase                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                | —      |
| D-018 | The SLO measurement period is `measurement_window` everywhere — column, ORM, schema, API field, console                                                                                 | `window` is reserved in Postgres. Renaming in the migration alone would have left the wire contract disagreeing with the column it maps to                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       | —      |
| D-019 | A JSON or time example in a migration comment must not put a colon straight before a word or digit                                                                                      | `op.execute` scans the entire string for bind parameters, comments included, so `{"below": 99.9}` became a parameter named `99` and the migration failed on a value nobody passed                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                | —      |
| D-020 | Casts in raw SQL are written `CAST(:p AS type)`, never `:p::type`                                                                                                                       | SQLAlchemy's `text()` does not treat a name as a bind parameter when a colon follows it, so `:id_0::uuid` reached Postgres unbound. This silently broke Merkle sealing and graph reconciliation — the two places the codebase builds VALUES lists by hand                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        | —      |
| D-021 | Cross-border transfer has four rungs: `prohibited` → `permitted_with_safeguards` → `permitted_with_consent` → `permitted`                                                               | Closes Q-007. Consent and Article 46 safeguards are different legal bases, and consent is the weaker of the two because it is withdrawable and carries no ongoing obligation, so a move from safeguards to consent is a real loosening. Collapsing them hid a material change behind a synonym                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   | —      |
| D-022 | Settings fields that read a delimited list from the environment are annotated `Annotated[list[str], NoDecode]`                                                                          | pydantic-settings JSON-decodes list fields before validators run, so the comma-separated `AAP_CORS_ORIGINS` documented in Compose raised `SettingsError` at import and the API could not boot. A unit test that passes the value as a kwarg never reaches this code path                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         | —      |
| D-023 | The worker's liveness signal is a heartbeat file refreshed in its dispatch loop, not an HTTP endpoint                                                                                   | It shares the API image and so inherited an HTTP health check against a server it does not run. A sidecar HTTP server would add a port and a failure mode to prove something the loop already knows                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              | —      |
| D-024 | Integration tests skip when no Postgres is reachable; they never start one implicitly                                                                                                   | `pytest` must stay runnable on a laptop with no Docker. Skipping is honest and visible in the summary line; silently spinning up a container makes a fast suite unpredictably slow                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               | —      |
| D-025 | `database_url` accepts `DATABASE_URL` and `AAP_DATABASE_URL`                                                                                                                            | The unprefixed name is required because platforms inject it, but every other setting is prefixed, so the prefixed name is what anyone reaches for. A validation alias turns `env_prefix` off for the field, and the default then absorbs the mistake in silence. Accepting both costs one line; the alternative cost a session of false green                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    | —      |
| D-026 | A helper that migrates a database must verify it reached head on the URL it was given                                                                                                   | `alembic upgrade head` against an already-migrated database is a successful no-op, and against the wrong database it is indistinguishable from the right one. Asserting the target's `alembic_version` afterwards is the only way a fixture can tell "migrated" from "did nothing"                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               | —      |
| D-027 | The seed generator calls `service.py`, never a repository, and is deterministic                                                                                                         | Raw inserts would populate states no code path can produce, so the console would show an estate the product cannot create. Going through services makes a seed run the broadest exercise of the write path in the project — it found the cross-border constraint drift in Q-011 on its first attempt. Determinism means a demo can be rehearsed and a bug reproduces                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             | —      |
| D-028 | The console container is built in `live` mode and reaches the API through its own origin via an nginx `/v1` proxy                                                                       | It was shipping in `mock` mode, so a fully healthy stack served fixtures that look exactly like a working product — nobody investigates a screen that looks right. Same-origin also removes a CORS preflight per request and a second hostname per environment. The nginx upstream is resolved through a variable so a recreated API container does not permanently break the proxy                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              | —      |
| D-029 | Windows `.cmd` scripts in `scripts/` mirror the Makefile rather than replacing it                                                                                                       | `make` needs `sh` and `openssl`, which this project's only developer does not have. The Makefile stays authoritative for CI. `aap.cmd` never pauses so it is safe to script; the double-clickable wrappers own that, because Explorer starts them with no arguments and can be detected reliably                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 | —      |
| D-030 | Local dev keys are generated with `cryptography`, not `openssl`                                                                                                                         | `make bootstrap` shelled out to `openssl`, which is absent on a stock Windows machine, so the first command in the README could not run. `cryptography` is already a dependency for signing and licensing, so openssl was contributing nothing but a portability failure                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         | —      |
| D-031 | An applied migration is never edited. Corrections ship as a new revision                                                                                                                | Closes Q-011. D-021 was applied by editing `0002` after it had run, so a fresh database got four cross-border rungs and an existing one kept three — both reporting revision `0005_assurance`. Reverting `0002` and widening in `0006` is the only option where the two populations converge. Where a revision written in the current session must change, downgrade through it and re-apply rather than edit, so the local database re-runs the new text                                                                                                                                                                                                                                                                                                                                                                                                                                                        | —      |
| D-032 | A finding marked `fixed` reopens when it recurs; `false_positive` and `accepted` stay closed. Any move to an unresolved state clears the resolution                                     | Re-raising an existing fingerprint only bumped `last_seen_at`, so a vulnerability that came back still read as fixed — the one interpretation that is certainly wrong. The other two states are human suppressions of findings that recur by nature, and reopening them refills the queue with rows somebody already dismissed, which is how a queue stops being read. Separately, `triage_finding` left `resolved_at` set, violating `findings_resolution_consistent` and returning a 500 from the database; `resolve_finding` had always cleared those fields going the other way                                                                                                                                                                                                                                                                                                                              | —      |
| D-033 | `pyjwt[crypto]` is the only JWT library. `python-jose` and `authlib` removed                                                                                                            | Both were declared and neither was imported anywhere. Three libraries on the security boundary is three to audit and to track advisories for. `pyjwt` takes the algorithm allowlist as a required argument rather than an option, which is exactly the mistake that matters — a verifier that trusts the token's `alg` header accepts `none` or an HMAC keyed on the public verification key                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     | —      |
| D-035 | A trust portal link is `/portal/{customer_slug}/{engagement_slug}`. Both halves, always                                                                                                 | `engagements_slug_unique` is `(org_id, customer_id, slug)`, so an engagement slug identifies a client's engagement only alongside that client. Matching on it alone found all five seeded clients at once and raised, which made the portal a 500 for the entire demo estate. There is no correct single-slug behaviour available: picking one of the five would show a client another client's estate, so the ambiguity had to be removed rather than resolved. The integration tests missed it because the fixtures generated a unique slug per client, which is the one arrangement the real data never has — they now share one by default                                                                                                                                                                                                                                                                   | —      |
| D-036 | The console's landing page is `/v1/home/summary`, and it exists                                                                                                                         | The screen called `/v1/dashboard/summary` from the day it was written and no such route was ever built. In mock mode it rendered fixtures and looked finished; in live mode it was an error, so the product's first screen had never worked against its own API. The new endpoint returns what the page shows and nothing more — no sparkline series, no distributions, no fourteen-day histogram — because each of those has a screen of its own and inventing them again here is how a landing page becomes unreadable. `home` owns no tables and composes other domains' services, which is why it is three files rather than the usual six                                                                                                                                                                                                                                                                   | —      |
| D-043 | No version label on the descriptor format. It evolves in place                                                                                                                          | Owner's instruction, verbatim: "No 0.1 or 0.2. we dont have any final version yet. we are still developing. so dont create any versions any where." Supersedes the design's recommendation to publish a 0.2 alongside 0.1. The existing `aap_version` field is left as it stands; nothing new branches on it. This is correct while there are no external consumers and becomes wrong the moment there is one, so it is recorded rather than assumed — the cost of reversing it later is a real migration path, and the cost of honouring it now is zero                                                                                                                                                                                                                                                                                                                                                         | —      |
| D-044 | Enforcement of model residency happens in the customer's LLM gateway, not in a proxy we write. We are the policy authority and the evidence layer                                       | LiteLLM already does region-filtered routing with `enable_pre_call_checks`, and Envoy handles the L7 tier. Writing a third is a large amount of code to arrive at a worse version of something proven. So we compile an agent's obligations into gateway configuration, expose a pre-dispatch decision endpoint driven by the *same* compiled result, and ingest the gateway's logs to audit it — with an integration test asserting the emitted config and the live decision agree, because two code paths that can disagree eventually will. Their docs also warn that provider fallbacks bypass model permissions unless `enforce_fallback_model_access` is set, so a residency policy can be defeated by a rate-limit failover; emitted config always sets it                                                                                                                                                | —      |
| D-045 | Plain-language change summaries come from deterministic templates over the structured changeset. An LLM may never be the source of truth or gate a release                              | The whole point is a non-technical reviewer trusting the summary. A tool that hallucinates "this change is safe" is worse than no tool, and one wrong summary destroys the trust permanently. Templates are auditable: every sentence carries the change path and the materiality rule id that produced it. An unclassified change resolves to `needs_review`, never to cosmetic — following `tfreport`'s rule that an attribute with no known impact rating falls back to the action default rather than being assumed benign                                                                                                                                                                                                                                                                                                                                                                                   | —      |
| D-046 | Probe verdicts are decided by deterministic oracles over recorded effects. An LLM judge is advisory, is consulted only on cases marked ambiguous, and can never flip a verdict          | This is the settled consensus in the red-teaming literature rather than our invention — `redcell` and REDAgentBench both insist on it, and with no judge configured a case degrades to `needs_review` instead of receiving a fabricated score. Execution-verified and judge-advisory counts stay separate all the way to the screen, because REDAgentBench's central finding is that collapsing them into one attack-success-rate conflates exposure, execution and adjudication. Oracles read effects (`run_steps`, `tool_usage_daily`, `policy_decisions`) rather than narrative, since an agent can state a constraint and violate it anyway — measured at nearly one in five confirmed violations                                                                                                                                                                                                            | —      |
| D-047 | Domain layering is declared once in `app/domains/layer_order.py` and enforced by a test that parses the real import graph                                                               | Four parallel agents produced a module-level cycle between `composition` and `assurance` in a single session, and the suite passed anyway because Python tolerated the import order. `AGENTS.md` rule 3 had been prose only, and both new domains were simply missing from the chain — an unenforced layering rule is a suggestion. The test derives the order from code so the document and the check cannot drift, and it asserts the graph is acyclic as well as correctly directed                                                                                                                                                                                                                                                                                                                                                                                                                           | —      |
| D-048 | The development stack's `web` service runs Vite from a source mount. The nginx target that bakes a bundle into the image is for real deployments only                                   | The baked target was being used in development, so the console served whatever was compiled the last time somebody rebuilt the image while every other service reloaded from disk. The two drifted by about six hours and a full session's work: four screens appeared broken because their routes were genuinely absent from the bundle being served, and nothing anywhere reported a problem — nginx was healthy and serving exactly what it had been given. A stale artefact presented as the current one is the worst available failure mode, because every other explanation gets investigated first                                                                                                                                                                                                                                                                                                        | —      |
| D-049 | Types for anything the API returns are generated from `openapi.json` and referenced as `Wire<"SchemaName">`. Hand-written types are reserved for view models assembled in the browser   | `openapi-typescript` and a `client` script had been dependencies since the first frontend commit and had never been run — `openapi.json` did not exist, so the script would have failed on first use. About a dozen types were retyped by hand instead and drifted: `PolicyVersion` claimed `version`, `digest`, `signed_by` and `signature_status` against an API returning `semver`, `rules_digest` and `published_by`. Those columns rendered blank and nothing failed, because a hand-written type agrees with itself. Generating them turned the drift into 94 compile errors in one pass, which is the only way a problem of that shape gets found                                                                                                                                                                                                                                                         | —      |
| D-050 | No mock API layer. The console always talks to a real backend                                                                                                                           | `src/mocks` was 2,629 hand-written lines mirroring 125 routes — a second, independent account of the same contract, and it disagreed with the real one in exactly the same places the console did. Fifteen dead request paths and a dozen wrong response shapes all returned 200 in mock mode. **A fake that agrees with your mistakes is worse than no fake, because it removes the feedback that would have caught them.** The justification for keeping it was frontend work without a backend, and `docker compose up` now provides Postgres, the API and Vite with hot reload in one command, so that cost no longer exists. Deleted rather than corrected: re-aligning 2,629 lines buys one day of agreement and then drifts again                                                                                                                                                                         | —      |
| D-051 | `npm run check:api` reads every `/v1/` literal out of the source and every route out of the spec, and fails the build on a mismatch                                                     | Fifteen of fifty-three console request paths pointed at routes that had never existed, mostly a missing domain prefix — `/v1/findings` for `/v1/assurance/findings`. No type checker can catch this: a path is a string, and the two halves of the mistake live in different languages. The check is external and mechanical for that reason. It ignores comments, because the natural way to document a removed path is to quote it, and quoting one would otherwise fail the build the comment exists to explain                                                                                                                                                                                                                                                                                                                                                                                               | —      |
| D-052 | `tests/smoke/sweep.py` calls every readable route against a seeded estate and fails on any 5xx                                                                                          | A 500 reached the user from a route no test touched: `column c.name does not exist`, raw SQL naming `customers.name` when the column has been `display_name` since 0002. Nothing could have caught it — unit tests open no connection, the model-drift test compares ORM declarations to Postgres while that query is a `text()` blob the ORM never sees, and no integration test called the endpoint. The sweep is deliberately crude, and crude is the point: it finds routes that are wired up, return 200 in nobody's test, and raise the moment a real row goes through them. Only 5xx fails it — a 404 for a subject the estate does not contain is a gap in the seed data, not a defect                                                                                                                                                                                                                   | —      |
| D-037 | The transaction commits in a custom route class, before the response is sent — not in the session dependency's teardown                                                                 | Closes Q-016. A `yield` dependency resumes after its handler returns, and on FastAPI 0.141 the exit stack that drives that resumption sits outside the router, so the commit ran after the response had already been handed to Starlette. A client that created something and read it straight back raced the commit and 404'd about half the time, which includes the console. Starlette's `request_response` awaits the handler to completion before sending anything, making the route handler the innermost point still guaranteed to precede the response. It also turns a failed commit into a 500 instead of a 201 describing a row that was never written. `route_class` has to be set on each domain router, not on the aggregate, because `include_router` re-creates each route as `type(route)` — so a test enumerates the app's own routes and fails if one holding a session is a plain `APIRoute` | —      |
| D-038 | A test that enumerates routes resolves FastAPI's `_IncludedRouter` through imported private names, and asserts the result is plausible rather than non-empty                            | FastAPI 0.141 stopped copying child routes onto the parent, so `app.routes` became four docs routes, three `APIRoute` and one opaque wrapper. The auth invariant filters for `APIRoute`, so it went from covering 47 endpoints to covering one **and still passed** — the exact failure this style of test exists to prevent. Importing the private names means a rename upstream is an `ImportError` at collection rather than a walker that silently returns nothing; matching on class names by string would fail open again                                                                                                                                                                                                                                                                                                                                                                                  | —      |
| D-039 | A declared component contributes several match keys — the raw name, the URL without its scheme, the host, and the last path segment — and the declared check is asked per calling agent | Descriptors hold `references.mcp_servers` as URLs; a runtime reports what the server calls itself. Exact matching marked 14 of 17 MCP servers on the demo estate as undeclared, all false alarms, which is worse than not checking because it trains people to ignore the column. Per-agent rather than per-estate because "some other team declared this tool" is no answer to "why is this agent calling it". The heuristic is the weak point of the reconciliation and the real fix is a stable server name in the descriptor — raised as Q-017 rather than smuggled in here                                                                                                                                                                                                                                                                                                                                  | —      |
| D-040 | The estate-level service-level figure is the share of service levels meeting their target, not the mean of their measured values                                                        | The old computation averaged raw measurements across service levels in different units — milliseconds and percentages in one mean — and reported `slo_attainment_pct: 1173.1`. A mean of mixed units is a category error with no correct denominator, so there was no way to fix it while keeping the name. The replacement is unit-free, bounded and answers the question people were reading it as anyway. Renamed to `slos_meeting_target_pct` so nobody carries the old reading forward                                                                                                                                                                                                                                                                                                                                                                                                                      | —      |
| D-041 | One time window in the top bar, shared by every operational screen, persisted per browser                                                                                               | A range picker per screen sounds more flexible and is worse: you compare a cost figure from one screen against a run count from another, they were measured over different weeks, and nothing on either page says so. Every React Query key carries the window, because without it switching from 7 days to 90 serves the 7-day answer out of cache under a "Last 90 days" heading — the worst kind of wrong, because it looks fine                                                                                                                                                                                                                                                                                                                                                                                                                                                                              | —      |
| D-042 | Charts are hand-drawn SVG primitives in `components/charts/`, not a charting dependency                                                                                                 | Four shapes cover every chart in the console — stacked area, ranked bar list, donut, and a sparkline that fits a table cell — at about 400 lines against roughly 150 kB for the smallest library that would do the same job. The saving is secondary; the real reason is that a chart library's defaults become the product's visual language, and this console needs the axis, the empty state and the tooltip to say specific things. Bars rather than a line in the sparkline because those series are counts of discrete days, and a line implies something continuous between them                                                                                                                                                                                                                                                                                                                          | —      |
| D-034 | Generic OIDC, with tenant identity resolved through an `identity_bindings` table rather than a claim we require                                                                         | Closes Q-004. Entra, Okta, Keycloak and Auth0 all reduce to an issuer, a discovery document and a JWKS, so one implementation covers them as configuration. Requiring an `org_id` claim only works when we own the provider; a customer authenticating against their own Entra tenant will not add a claim for us, and asking turns a two-week pilot into a two-quarter one. They give us an issuer and a tenant id, we bind it. The binding key is (issuer, claim, value) because a value is only meaningful alongside who asserted it, and one unbound claim never falls through to the next — that would answer with a weaker assertion than the caller made                                                                                                                                                                                                                                                  | —      |
| D-053 | Observe is the canonical detailed Execution plane; operations receives a durable, content-free projection rather than an independent SDK write | One measurement path prevents conflicting run/trace totals while preserving operations-based assurance and composition consumers; closes Q-020 | `docs/architecture/agent-observability-plan.md` |
| D-054 | Retain the public `aap-trace` distribution and `aap_trace` import identity | Owner selected compatibility over a product-name migration; closes Q-021 | — |
| D-055 | Playwright is approved as a web development dependency for execution-workspace browser certification | Graph, inspector, timeline and live reconnect behavior cannot be certified by type checking or manual route sweeps; closes Q-022 | — |
| D-056 | User Activity is first-class alongside Agent Execution, with per-user agent/model/SDK/tool/MCP-tool metrics and explicit telemetry coverage | The product must explain what users did through instrumented/controlled paths without claiming visibility into uninstrumented third-party clients or becoming covert monitoring | `docs/architecture/agent-observability-plan.md` |
| D-057 | The audit `category` vocabulary is the Pydantic `Category` enum; migration `0017`'s CHECK constraint follows it, and a unit test asserts the two agree | The two lists had drifted on the day they were written — the constraint allowed `registry`/`enforcement`/`payload`/`lifecycle` while the API emitted `mcp`/`routing`/`data`/`admin`, so four of seven categories would fail at INSERT. Subsystem-named categories won because that is how an operator navigates; `outcome` and `severity` already answer "was it denied" and "how bad" | — |
| D-058 | Bounds that exist in both the API and the database are deliberately unequal, with the API stricter | The audit `detail` cap measures compact JSON at the boundary and jsonb's binary layout in the CHECK. These are different quantities, so equal numbers make some records pass validation and then fail inside Postgres, turning a 422 that names a field into a 500 from a thousand-event batch. Slack in the database direction keeps the constraint a backstop against writers that bypassed the API | — |
| D-059 | Every list over a table that grows with request volume is keyset-paginated; offset pagination is reserved for tables that grow with headcount | `security_audit_events` is partitioned and expected in the billions, where `OFFSET n` scans and discards n rows per page. Members, teams and roles are bounded by how many people a customer employs, so offset there costs nothing and gives the console a total count it can show | — |
| D-060 | The `nexus-dashboard` six-destination shell and visual language are the console target; its fixture arrays are not a runtime data source | The owner explicitly directed the complete visual migration. Existing service APIs remain authoritative and each Nexus layout is mapped to them or gains a vertical backend slice, preventing the static reference app from becoming a second mock backend | `docs/architecture/account-access-console-redesign.md` |
| D-061 | AAP-owned model and MCP gateways are mandatory enforcement boundaries; this supersedes D-044's customer-gateway-only boundary and closes Q-023 | The owner explicitly directed AAP to be the company/provider bridge, keep provider credentials server-side, mediate MCP access and route every agent through AAP policy. Signed route snapshots and customer egress controls remain independent evidence rather than being discarded | `docs/architecture/account-access-console-redesign.md` |
| D-062 | Platform Keys are the issued, revocable machine identity, optionally bound to an agent and verified member; provider credentials are never handed to agent code | Answers Q-012/Q-019 with the owner's requested platform-issued authentication model, works in air-gapped deployments, and gives model/MCP telemetry one stable attribution path | — |
| D-063 | `org_id` is an internal isolation key; browsers never select or transmit it. Entra `tid` resolves the account, while employee access requires a pending invitation before first-sign-in identity binding | Removing the isolation key would contradict D-006/D-034 and break RLS, Observe and gateway contracts. Removing it from profiles and browser state fixes the user problem without weakening tenant isolation; invitation-gated JIT prevents every employee in a customer tenant from self-enrolling | — |
| D-064 | `design/` is the authoritative specification for the control-plane rebuild, and the current implementation is prior art plus a migration source rather than a constraint. Diagrams are generated by `design/diagrams/build.mjs` and must pass `validate.mjs` with zero layout defects | Eleven sessions of feature work on an unfinished identity model is what produced "unknown organisation" on every screen. A specification that is read before code, and a diagram set that is a diff rather than a redraw, is the cheapest available correction. Generated diagrams also stay consistent as the design changes, which hand-drawn ones do not | — |
| D-066 | **The capability, not MCP, is the top-level governed object.** `mcp.tool` becomes one kind in a registry that also holds `shell.exec`, `net.http`, `fs.read`, `fs.write`, `vcs.write`, `cloud.api`, `db.query`, `agent.delegate` and `memory.write`. `mcp_servers` → `capability_sources`, `mcp_capabilities` → `capabilities`, `mcp_grants` → `capability_grants`. Design-set decision D-08 | The reference incident of 25 April 2026 travelled `fs.read → shell.exec → net.http` and touched neither gateway `[B-01][B-02]`. An architecture whose only enforcement points are absent from its own canonical incident is mis-scoped, not incomplete. Nothing in `design/06` is dropped — it is re-homed as one binding | `design/15-capability-governance.md` |
| D-067 | **The MVP is a read-only agent action ledger, replacing the ten-phase plan.** Claude Code + Cursor + Copilot, `shell.exec` / `net.http` / `fs.read` observed and graded, shadow-agent and credential-exposure discovery. Enforcement, credential brokering and composition drift move to V1. Design-set decision D-17; supersedes D-065 | The old plan produced a security outcome at phase seven and built three commodity layers first. A read-only collector needs no architecture review, adds no latency, cannot break a developer's day, and ends with the customer holding their own evidence that they need the enforcement we sell next. D-065's ordering insight (identity before grants) is preserved inside it | `design/17-research-conclusions.md` §7 |
| D-068 | **Cedar is the policy engine; administrators author in a structured UI that compiles to it.** Cedar is the audit artefact and the simulation target, never the authoring surface. Design-set decision D-13 | Its native `principal / action / resource / context` shape is the action model already `[B-73]`, and it compiles to SMT with machine-checked proofs `[B-74]` — which turns "will this change deny something that is allowed today?" into a solver query instead of a replay harness. Rego is more expressive and cannot answer that question | `design/14-ai-identity-and-authorization.md` §7 |
| D-069 | **Every control carries an enforcement grade A–E, and it is a mandatory column on every decision row.** A = mediated, B = interposed with a real veto, C = vendor-enforced and attested, D = observed after the fact, E = not covered. `unknown` counts as E. No coverage figure ships without its denominator. Design-set decision D-09 | The previous framing — "in the editor we configure, at the gateway we enforce" — overstates the gateway for Cursor and understates a blocking `PreToolUse` hook for Claude Code, which genuinely prevents the call `[B-31]`. A binary claim is wrong in both directions, and the first incident in an ungraded blind spot costs the customer | `design/12-strategic-thesis.md` §5 |
| D-070 | **Cursor prompt DLP is withdrawn as a claim.** Cursor's backend is the intermediary for model traffic `[B-41]`, so content reaches Cursor before it reaches us, and base-URL routing requires our data plane to be internet-reachable rather than outbound-only. What we sell for Cursor is Grade A MCP mediation `[B-42][B-43]`, Grade B hooks `[B-33]`, Grade C attestation, Grade D reconciliation. Design-set decision D-11 | A control claim that a customer's own network trace disproves is worse than no claim. This also corrects the outbound-only-egress promise in `design/01` | `design/05-model-gateway.md` |
| D-071 | **The credential broker replaces the token vault as the primary control.** Per-task leases: short-lived, audience-bound (RFC 8707), sender-constrained (RFC 9449 / RFC 8705), scoped to the least authority the task declared. Design-set decision D-10; extends D-062 rather than reversing it | It is the only control that survives a bypassed path, and it is the direct answer to the reference incident's stated probable cause — *an over-privileged, long-lived account-scoped token accessible from the agent's filesystem workspace* `[B-01]`. Platform Keys (D-062) remain the machine identity; the broker is what that identity is allowed to mint | `design/14-ai-identity-and-authorization.md` §5 |
| D-072 | **The identity chain is `Human → Agent → Agent Version → Agent Instance → Session → Task → Action`.** Every action resolves to exactly one human root with a recorded `root_human_basis`; a service identity may never be a root; authority attenuates and never widens across a delegation hop; depth is capped. Design-set decision D-12 | "Who is responsible for this AI action?" has no answer in a three-principal model, and it is the first question asked in every investigation and every security review. RFC 8693 `sub`/`act` gives the semantics without inventing terminology | `design/14-ai-identity-and-authorization.md` §1–§4 |
| D-073 | **The executable development sequence is F0 → F1 → F2 → M1 → M3 → M4 → M2 → M5 → V1 → packaging. The MVP is read-only; Claude Code is first and Cursor must ship before the demo.** `organizations`/`org_id` remains the MVP tenant root; human sessions are `auth_sessions`, agent contexts are `agent_sessions`, and ledger rows are `agent_actions`. The old `phase-00`–`phase-09` prompts are historical and non-executable | Regression of all 23 prompts found two conflicting programs, revision collisions with real head `0022`, duplicate gateway/MCP/Observe work, and naming collisions. This order validates the cross-vendor event contract before enforcement or commodity modules and gives schema, UI and migration ownership to exactly one prompt each | `design/prompts/README.md`, `design/prompts/f1-ledger-schema.md` |
| D-074 | **The navigation manifest is authored by the server and the browser renders it. One component, `Shell.tsx`, consumes it; `Rail.tsx` and `TopBar.tsx` are deleted.** An entry is filtered out by permission, by unlicensed module or by an off capability flag, and a group left empty by that filtering is removed rather than rendered as a heading | A navigation hardcoded in the browser cannot be filtered by entitlements the browser is not allowed to be the judge of, and the second copy is where the disagreement lives: two navigations had already drifted into disagreeing about which product this is. Deleting the orphans rather than leaving them unreferenced matters because "unused" is a fact about today — `inv_single_nav_source` makes it a fact about tomorrow. Filtering server-side also means an unlicensed module is absent from the response, not merely hidden by CSS | — |
| D-075 | **`AAP_PRODUCT_MODE` (default `ledger`) selects which product an install is, and it is branched on in exactly one file — `HomeRoute.tsx`. `AAP_ASSURANCE_CAPABILITIES` is an allowlist that defaults to empty** | D-067 made the MVP a read-only ledger, but the accreditation product is written, tested and shipping in the same binary, so "delete it" and "show it" are both wrong. A mode plus an opt-in allowlist means a fresh ledger install leads with the ledger while an operator can name individual surfaces back — and defaulting the flags to empty rather than full is the direction that fails safe, since an unasked-for surface is a support conversation about a product the customer did not buy. One branch point because the alternative is the same conditional in the route table, the shell and three layouts, which is how the two navigations diverged in the first place | — |
| D-076 | **`DataBoundary` renders all four states; `ErrorState` is a leaf that displays the `reason` and `next` the API already returned. A project is a filter and never a gate** | F0 made every error carry a reason and a next action, and the console was re-deriving both from the HTTP status — a second, worse account of something the server had already decided. The boundary also fixes the shape of the mistake: in `ObserveSuiteLayout` it wraps only the project selector, with the `<Outlet />` outside it, so a failing project list degrades one control instead of blanking the ledger behind a "select a project" wall. That wall is the specific regression `design/09` rule 5 exists to prevent | `design/09-frontend-and-api-contract.md` |
| D-077 | **Icons are imported one module at a time (`lucide-react/dist/esm/icons/<name>`); the barrel is forbidden by `inv_no_lucide_barrel`, and `src/types/lucide-icons.d.ts` types the deep paths.** `import type` from the barrel stays legal | The barrel re-exports ~1,600 modules, and Vite has no `optimizePackageImports`, so it cannot be optimised away after the fact — it has to not be written. The declaration file is the part that makes the rule followable rather than aspirational: the package ships no per-icon types, so before this the honest choice was a typed barrel or an untyped direct import, and everyone reasonably picked types. Type-only imports are exempt because they are erased before a bundler sees them | — |
| D-078 | **Ledger idempotency lives in a separate unpartitioned `agent_action_receipts` table, uniquely keyed on `(org_id, event_id)`. The ledger itself carries no unique constraint on `event_id`** | Postgres requires the partition key in any unique constraint on a partitioned table, so the only constraint expressible on `agent_actions` is `UNIQUE (org_id, event_id, occurred_at)` — which accepts a retried event whose `occurred_at` was corrected in flight, and that is precisely the duplicate a retrying collector produces. Giving up partitioning to get the constraint is the worse trade: monthly range partitions are what make retention a `DROP TABLE` instead of a delete across hundreds of millions of rows on the one table that must never be rewritten | `design/prompts/f1-ledger-schema.md` |
| D-079 | **`enforcement_grade` is NOT NULL, `unknown` is a permitted value, and `unknown` reads as `E` through exactly one function on each side (`effective_enforcement_grade()` in SQL, `ActionDecision.effective_grade` in Python). No query compares the column to a grade directly** | A nullable grade makes "how much of this estate is actually controlled" unanswerable, and a collector legitimately knows what happened before it knows what it could have done about it — so refusing the row is wrong too. `unknown` records that gap explicitly and the mapping makes the ungraded population count as *uncovered* rather than quietly as protected, which is the direction a coverage number must fail in. An enforcing outcome at effective grade E is then a contradiction and is refused at the boundary and at the column: E means not covered, so nothing can have denied, masked or rerouted it | `design/12`, `design/prompts/f1-ledger-schema.md` |
| D-080 | **`agent_actions` carries no foreign key other than the tenant column, and the ledger's own vocabularies are `Text` with `CHECK` rather than Postgres enums** | An action taken by an agent that was later retired, against an MCP server that was later deleted, is exactly the action an investigator wants six months later — a foreign key would either block the delete or take the evidence with it. The `CHECK` choice is the same argument one layer down: `ALTER TYPE ... ADD VALUE` cannot run in a transaction with other DDL and cannot be reversed, so an enum on an evolving vocabulary turns every new capability kind into a migration that cannot be rolled back. `observed` is likewise its own outcome rather than folded into `allow`, because the MVP ledger is read-only and calling an unmediated action "allowed" claims a decision we never made | `design/prompts/f1-ledger-schema.md` |
| D-065 | The phase order is P0 stabilise → P1 tenancy/identity → P2 authorization/visibility → (P3 model gateway → P4 catalogue/routing) ∥ (P5 MCP gateway → P6 data protection) → P7 activity/scale → P8 hierarchy/cost → P9 packaging. **This reverses the earlier plan, in which MCP control was Phase 1** | An MCP grant names a subject; with the subject model unfinished, grants were issued to a member while Cursor authenticated as a workload, which is exactly why the registry listed zero tools. Ordering identity first removes a class of defect rather than one instance of it. No MCP capability is dropped — `design/06-mcp-gateway.md` and `prompts/phase-05-mcp-gateway.md` carry all of it | — |




---



## Open questions

Carried between sessions until closed. Do not silently resolve one — raise it.


| ID        | Question                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | Blocking                                                                                                                                                                        |
| --------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Q-026     | **Three market/validation decisions remain after D-073 resolved Q-L and Q-M.** **Q-N** credential brokering stays V1 unless a design partner requires it earlier. **Q-P** who signs — platform/DevEx, AppSec, CISO or CFO — remains unsettled in evidence `[B-14]`. **Q-Q** asks whether Grade B, a hook on a user-administered machine, is acceptable as a control. Q-Q must be answered before V1b enforcement, not before the read-only MVP | Q-N does not block F0–M5; Q-P blocks packaging/pricing; Q-Q blocks V1b and determines whether the long-term thesis narrows to broker + MCP mediation |
| Q-024     | **Partially resolved by session 32.** Closed: **D-A** first deployment mode (SaaS control plane + customer data plane; five modes reduced to three) · **D-D** self-hosted `route_internal` (moot — no model gateway in the MVP) · **D-G** the ~35 accreditation tables (park). Still open, all non-blocking: **D-B** Cursor Enterprise at the pilot, which decides Grade C versus Grade E for Cursor · **D-C** directory source of truth, recommendation SCIM · **D-E** retention versus legal hold · **D-F** who distributes client configuration, recommendation the customer's endpoint team. Original wording: seven design decisions await the owner: D-A first deployment mode · D-B Cursor Enterprise availability at the pilot · D-C directory source of truth · D-D is a self-hosted model available for `route_internal` · D-E retention vs legal hold · D-F who distributes client/MDM config · D-G park or carry the 35 accreditation/compliance tables. Answer them in the table in `design/README.md`; each names the phase it blocks, and D-A, D-C and D-G block Phase 1 |
| Q-001     | Regulatory control text is paraphrased in the `0002` seed. Needs legal review before any pack reaches a customer                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  | accreditation packs, not current work                                                                                                                                           |
| Q-002     | Are engagement-level framework requirements needed, or is customer-level enough? Currently customer-level only                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    | `engagements` slice                                                                                                                                                             |
| Q-003     | Does `agent_versions.descriptor_json` need a size cap? A large descriptor with inline prompts could bloat the GIN index                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           | `registry` slice                                                                                                                                                                |
| ~~Q-004~~ | ~~Identity provider for the console — Entra ID first, or generic OIDC first?~~                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    | **Closed session 8** — generic OIDC, D-034. Named providers are configuration                                                                                                   |
| ~~Q-005~~ | ~~45 mypy strict errors from untyped third-party stubs~~                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | **Closed session 6** — fixed by narrowing and boundary casts, not by relaxing strict                                                                                            |
| Q-006     | Is `customers.sector` the right driver for framework defaults, or should it be the client's regulator? A UK bank and a UK retailer differ more by regulator than by sector                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        | `frameworks` slice                                                                                                                                                              |
| ~~Q-007~~ | ~~Is~~ `permitted_with_consent` ~~the same rung as~~ `permitted_with_safeguards`~~?~~                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             | **Closed session 7** — no. Four distinct rungs, D-021                                                                                                                           |
| Q-008     | Four domains still have token coverage: `bom` (1 test), `attestation` (3), `frameworks` (4), `sla` (5). `home` joined them in session 9 — it grew from three files to the widest composition in the codebase and has no tests of its own, which is how the 1173.1% service-level figure (D-040) reached a screen. `portal` was closed out in session 8 at 15 tests and is the pattern to copy — a pure isolation function unit-tested for its edge cases, the rest against real Postgres with fixtures built through the service layer. `registry`, `evidence` and `graph` were covered in session 7; `assurance` has findings-lifecycle tests but not probes or posture          | test strategy                                                                                                                                                                   |
| ~~Q-011~~ | ~~D-021 was implemented by editing migration~~ `0002`~~, which was already applied~~                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              | **Closed session 8** — `0002` reverted, `0006` widens, D-031                                                                                                                    |
| ~~Q-012~~ | ~~Machine identity: OAuth client credentials or platform-issued API keys?~~ | **Closed session 28** — issued/revocable Platform Keys, optionally agent/member-bound, D-062 |
| Q-013     | **Production console login is partial.** Entra OIDC authorisation-code+PKCE auto-start, API-side issuer-claim account/member discovery and dev net-ID fallback are implemented; the org picker is gone. Still open: which issuer operates SaaS tenants and the refresh-token/session renewal policy. | any external demo of multi-tenant SaaS |
| Q-014     | **RBAC exists, but directory provisioning policy is unsettled.** Eight fixed roles, member/team grants, scoped permissions and separation of approval duties are implemented. Do Entra groups map automatically to those roles, remain manually managed against the bound member, or use a hybrid with protected roles requiring manual approval? | production administration and joiner/mover/leaver automation |
| ~~Q-016~~ | ~~A write is not reliably readable immediately afterwards~~                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       | **Closed session 9** — the commit ran in dependency teardown, after the response. `TransactionalRoute` moves it ahead of the response, D-037. Three consecutive smoke runs pass |
| Q-017     | **An MCP server has no stable name in the descriptor.** `references.mcp_servers` holds a URL; a runtime reports whatever the server calls itself. Reconciliation therefore matches on a normalised set of keys — host, last path segment, raw string (D-039) — which is a heuristic, and the weak point of the one check this product is uniquely able to make. A server reachable at two URLs, or renamed behind the same URL, defeats it in opposite directions. Should the AAP descriptor carry a `name` alongside `url` for each MCP server, making the match exact? That is a schema change and a version bump, so it wants a decision rather than a quiet addition          | the credibility of "undeclared tool" as a finding                                                                                                                               |
| Q-018     | Console search filters an already-loaded page of 200 agents in the browser. Instant and correct at that size, neither past a few thousand. A `GET /v1/search` across agents, releases and findings is the obvious answer; the question is whether it is worth building before anyone has an estate that large                                                                                                                                                                                                                                                                                                                                                                     | console usability at scale; not blocking                                                                                                                                        |
| ~~Q-019~~ | ~~Nothing can report a run without the development bypass.~~ | **Closed session 28** — Platform Keys authenticate collector/Observe/model/MCP workload paths, D-062 |
| Q-015     | **Row-level security is inert as deployed.** All 40 policies exist and `FORCE ROW LEVEL SECURITY` is set, but the application connects as `aap`, which is `rolsuper` and `rolbypassrls` — so every policy is skipped. Queries still filter by `org_id` explicitly, which is the primary mechanism, but the backstop this document claims is not currently a backstop. Fixing it means a non-superuser application role with explicit grants, which touches the migration that owns the schema, Compose, the Helm chart and the BYOC install docs. Separate owner role from runtime role now, or accept it until first deployment?                                                 | the tenant-isolation claim in a security review                                                                                                                                 |
| Q-010     | `agent-assurance/` is not a git repository. Seven sessions of work exist only as files in a folder, inside the home-directory repo, untracked. There is no history, no way to see what a session changed, and no backup. Initialise a repo here (and push where)?                                                                                                                                                                                                                                                                                                                                                                                                                 | everything; this is the largest non-technical risk in the project                                                                                                               |
| Q-009     | **Initial customer provisioning remains open.** Employee invitation and first-sign-in identity binding now work after an account and Entra `tid` binding exist, but creating that first account/binding still needs an install-admin flow. Choose `aap admin bootstrap-account`, a first-run console flow, or an install-token endpoint. Company display name and manager hierarchy should be imported from Microsoft Graph/SCIM only after tenant-admin consent, never inferred from an email domain. | first production SaaS customer onboarding |
| ~~Q-020~~ | ~~Should detailed execution truth become canonical in Observe with a durable content-free operations projection?~~ | **Closed session 19** — yes, D-053 |
| ~~Q-023~~ | ~~Approve the Assurance-Native Agent Gateway direction.~~ | **Closed session 28** — owner explicitly directed AAP-owned model/MCP adapters as the authenticated company/provider bridge; D-061 |
| ~~Q-021~~ | ~~Should the public SDK identity change to `nexaguard-agent`?~~ | **Closed session 19** — no; retain `aap-trace` / `aap_trace`, D-054 |
| ~~Q-022~~ | ~~May the web package add `@playwright/test` for browser certification?~~ | **Closed session 19** — yes, D-055 |


---



## Invariants under test

These are the assertions that must never regress. Add to this list, never remove from it.

**F2 UI structure (session 35).** Four source-tree invariants in
`check-runtime-contract.mjs`, plus the navigation manifest's own suite. All run; none of
them observes a browser, which is the limit to read them with.

- `inv_single_nav_source` — `Shell.tsx` exists, and no file imports `Rail.tsx` or
  `TopBar.tsx`, both of which are deleted. `check-runtime-contract.mjs`. **(run, 168
  files)**
- `inv_no_lucide_barrel` — no value import from `lucide-react`; deep per-icon paths only.
  `import type` is exempt and deliberately so, because `src/types/lucide-icons.d.ts` needs
  it to type the deep paths at all. `check-runtime-contract.mjs`. **(run, 168 files)**
- `inv_data_boundary_exists` — `LedgerHomeScreen.tsx` and `ObserveSuiteLayout.tsx` render
  their four states through `DataBoundary`. Honest about its scope: it names the two
  ledger entry points rather than sweeping the tree, because the legacy assurance screens
  still hand-roll their states and a tree-wide version would be satisfied by an unused
  import. `check-runtime-contract.mjs`. **(run)**
- `inv_grade_chip` — `EnforcementGrade.tsx` and `grades.ts` both exist, every grade A–E
  plus `unknown` is handled, and `unknown` is labelled "Ungraded" rather than blank or
  rounded up. `check-runtime-contract.mjs`. **(run)**
- **Navigation manifest suite** — `tests/unit/test_console_navigation.py`, 25 tests.
  A fresh ledger login leads with the ledger; the assurance product is absent from it; the
  ledger group reuses the existing `/observe` routes rather than inventing parallel ones;
  admin and MCP survive in both modes; every declared capability flag is consumed by some
  entry and every flag defaults off; a missing permission or an unlicensed module removes
  the link; an emptied group disappears instead of rendering a heading; no two entries
  claim the same URL subtree; every path appears exactly once; every declared permission
  exists. **(run)**

The last two are the ones worth keeping. "Every declared flag is consumed" catches a flag
that was renamed on one side only — which would otherwise present as a surface that can
never be switched on, with nothing failing. "No two entries claim the same URL subtree"
catches the specific way the old navigation broke: two groups both owning `/observe`, so
which one highlighted depended on array order.

**F0 console contract (session 34).** Five named invariants, and where each one actually
runs. Two are properties of the web source tree rather than of a running app, so they are
enforced by `services/web/scripts/check-runtime-contract.mjs`, which `npm run build` and
`npm run check:runtime` both invoke.

- `inv_every_error_has_reason` — every error response carries `reason`, `message`,
  `detail`, `next` and `request_id`, with the reason drawn from the closed vocabulary in
  `design/02` and agreeing with the HTTP status. Swept across every readable route, plus a
  malformed body (422, which used to be a bare Pydantic list the console could not render)
  and an unknown path. `tests/unit/test_console_contract.py`. **(run, 195 cases)**
- `inv_dev_provider_requires_dev_mode` — the `development` provider raises
  `provider_disabled` (403) in every environment except `development`, and signs in only
  domains it owns. `tests/unit/test_console_contract.py`. **(run)**
- `inv_no_session_without_member` — a refused sign-in sets no cookie **(run)** and writes
  no `auth_sessions` row **(db, unrun)**. The HTTP half is in
  `tests/unit/test_console_contract.py`; the row half is in
  `tests/integration/test_auth_sessions.py` and has never executed.
- `inv_no_build_time_auth` — no `VITE_OIDC_*` or `VITE_ENTRA_*` read anywhere in
  `services/web/src`. Identity configuration is a server answer, not a build argument.
  `check-runtime-contract.mjs`. **(run, 164 files)**
- `inv_bootstrap_is_single_request` — one call site per identity endpoint:
  `/v1/session/bootstrap` belongs to `useBootstrap.ts`, `/v1/members/me` to
  `platformQueries.ts`, and `/v1/access/me` to nobody, because the bootstrap already
  carries it. `check-runtime-contract.mjs`. **(run)** Honest about its limit: it proves
  one call site, not one call — which is the half that regressed in practice, since every
  extra request the shell made arrived as a new component fetching identity on mount.

Two further guards were added alongside them: the API client may not read `sessionStorage`,
`localStorage` or an `Authorization` header (the credential is an HttpOnly cookie it cannot
see by construction), and a machine-credential rejection must be byte-identical whether the
credential was absent, malformed or unrecognised — asserted by comparing the three
responses to each other rather than to a literal, which is what the test's name always
claimed and the literal never checked.

Entries marked **(db)** are now proven against a real PostgreSQL 16 by
`tests/sql/invariants.sql` or `tests/integration/`, not merely asserted above the
database.

Entries marked **(db, unrun)** have their test written in one of those two places and have
**never been executed**, because migration `0017` has not been applied and no PostgreSQL was
reachable in session 25. They are the weakest entries in this list: a test that has never
run is not evidence that the invariant holds, and the marker exists so nobody reads one as
if it were. Each becomes **(db)** on the session that applies `0017` and runs them.

- A verified employee cannot self-enrol merely by belonging to a bound Entra tenant; an
  exact pending invitation is required, and first sign-in binds the immutable
  issuer/subject before activation. **(db)**
- Evidence, release changes and agent versions cannot be updated or deleted (database triggers). **(db)**
- No evidence text field exceeds 512 bytes; a malformed `content_digest` and an unknown
`detected_by` are both refused at the column. **(db)**
- An evidence event lands in its month's partition, never the parent and never the
catch-all. **(db)**
- An event cannot be half-anchored: a batch id without a leaf index, or the reverse, is
refused. **(db)**
- Anchoring a batch stamps every event in it, and a second attempt on the same events is
refused rather than silently re-anchoring. **(db)**
- Unsealed events come back in leaf order, which is what makes the Merkle root
reproducible by anyone reading the same table. **(db)**
- Two tenants may register the same agent URN; neither can see the other's. **(db)**
- Blast radius walks the graph transitively and terminates on a cycle. **(db)**
- Re-declaring an edge keeps one row; retiring declared edges leaves the still-declared
ones alone. **(db)**
- Every tenant-scoped query filters by `org_id`; every table with a mandatory `org_id`
has row-level security enabled and forced. It is intended as the backstop but is not
one yet — the application role bypasses it (Q-015). **(db)**
- Two clients of the same consultancy cannot see each other through the portal. They
share an `org_id`, so `engagement_id` is the only thing separating them: the agent
list, the accreditation state, the SLO figures and the pack download all carry that
predicate, and a pack id belonging to another engagement is not fetchable through this
one's slug. **(db)**
- Every `/v1` GET route, enumerated from the application rather than from a list,
refuses a request with no credential. The exemptions are named with their reasons and
the inverse is asserted too, so a new open endpoint cannot be added to the exemption
set unnoticed. This test found two unauthenticated endpoints the day it was written.
- An `X-Org-Id` header is not a credential. It is read only under the development
bypass, which `Settings` refuses outside `AAP_ENVIRONMENT=development`.
- A token is rejected unless it is signed by a current key of the configured issuer,
names this service in `aud`, and carries `sub`, `iat` and `exp`. `alg` comes from
configuration, never from the token, and only asymmetric algorithms are permitted —
a verifier that accepts HMAC treats the public verification key as a signing secret.
- A rejection never says which check failed. The reason is logged, not returned.
- An unreachable identity provider is a 503, never a 401, and cached keys are served
past their TTL rather than failing. The provider's availability must not become ours.
- An unknown key id refetches the key set at most once per refresh interval. `kid` is
attacker-controlled and unauthenticated, so an unbounded refetch makes us an amplifier
pointed at the customer's identity provider.
- One tenant claim resolves to at most one organisation, enforced by a partial unique
index so revoked bindings stay on the table without blocking their replacement. An
unbound claim fails rather than falling through to the next claim, which would answer
with a weaker assertion than the caller made. **(db)**
- A finding cannot be in a resolved state without `resolved_at`, or in an unresolved one
with it, through any transition — including re-raising a fingerprint that is already
closed. **(db)**
- A `byoc` deployment cannot boot multi-tenant; an `airgap` deployment cannot enable telemetry.
- The semantic differ is order-independent: reordering a model list produces zero changes.
- A customer slug is unique within an organisation, never globally. **(db)**
- A version's semver is unique within an agent. **(db)**
- Reference-data rows (`org_id IS NULL`) are readable by every tenant and writable by none. **(db)**
- The evidence vocabulary is closed and single-sourced: the Python `EvidenceKind` enum,
the Postgres `evidence_kind` type and the seeded control mappings agree, and a mapping
naming an unknown kind is refused. Two migrations had already drifted here once. **(db)**
- Readiness buckets partition the scope: `answerable + narrative_only + unmapped + not_applicable == in_scope`, and `partial <= answerable`. A leak here would misreport
coverage in a client conversation.
- A narrative-only control is never counted as a gap, or coverage becomes unreachable.
- A contact role change closes the previous validity window rather than overwriting it,
so an approval made last quarter still names who reviewed it.
- An engagement's permitted and prohibited region sets are disjoint, it cannot end before
it starts, and its cross-border stance must be one of the four known rungs. **(db)**
- The CI gate and the console reach the same verdict for the same descriptor pair — same
accreditation impact, same material and review counts. They run one engine, and this
test is what keeps it that way.
- Every verdict names at least one rule id, including the unclassified fallback. A
material verdict nobody can trace to a rule cannot be argued with, audited or tuned.
- An unrecognised value on a governed ladder escalates to review. Silence on a value the
engine does not understand is the failure mode that lets a real change through.
- Renaming a team, or any same-rung vocabulary change, is immaterial. A gate that blocks
on cosmetic edits gets switched off, and then it protects nothing.
- A Merkle inclusion proof verifies against the published root, leaf-first, per RFC 6962,
and a tampered digest fails that check. The smoke run recomputes the root client-side
from the proof alone, which is the calculation an external auditor would reimplement.
- Settings are read hermetically in tests: a hostile `AAP_*` environment or a stray
`.env` on the developer's machine cannot change a test outcome in either direction.
- The database URL is honoured under both `DATABASE_URL` and `AAP_DATABASE_URL`, and an
environment variable always beats the built-in default. The default silently winning is
what let a suite migrate the wrong database and call it a pass.
- The integration fixture proves it reached head on the database it was handed. A
migration helper that cannot distinguish success from doing nothing is worse than none.
- The same seed produces the same estate, down to the descriptor contents. **(db)**
- Seeding twice does not double the estate, so bringing the stack up again is safe. **(db)**
- A seeded estate leaves no evidence older than the seal lag unanchored, and its chain
spans more than one batch — one batch proves nothing about a chain. **(db)**
- Every seeded agent has a current version and a named owner. Either missing renders a
console row with holes and leaves drift with nothing to compare. **(db)**
- CLI output never raises on a console that cannot encode it, and `--json` stays valid
ASCII regardless of console encoding.
- The CLI distinguishes "could not run" (exit 1) from "blocked" (exit 2). Conflating them
teaches people to ignore both.
- Rule ids are unique, every rule carries a rationale, and every id the engine can emit
resolves through `describe_rule` — including the two fallbacks kept out of evaluation.
A collision would silently drop a rule from the lookup while it kept firing.
- A write is readable by the request that follows it. Every route holding a database
session commits before its response is sent, enumerated from the application so a
router added next month cannot quietly opt out, and a commit that fails surfaces as a
500 rather than after a 201 has already gone out.
- Route enumeration finds the whole application, not a fraction of it. The walker
resolves FastAPI's include wrappers and is itself asserted to find a plausible number
of endpoints, because a walker that returns nothing makes every test built on it pass.
- A run report is replay-safe. The same report sent twice opens one run, and a terminal
report replayed after the run has closed is ignored rather than failing the batch it
arrived in. **(db)**
- A run that has finished carries an end time and a terminal outcome, and cannot end
before it started — checked at the schema so a bad report is a 422 naming the field,
and at the column so nothing else can write one. **(db)**
- Duration is computed from the reported timestamps, never taken from the reporter. Two
SDKs measuring it differently would make latency incomparable across the estate.
- A batch is collapsed to one row per tool bucket before it reaches the database. A
single statement cannot hit the same row twice through `ON CONFLICT`, so this is a
correctness requirement, not an optimisation. **(db)**
- An in-flight run is not counted as instantaneous: the latency percentiles skip null
durations rather than treating them as zero. **(db)**
- A refusal is not a failure. Guardrail refusals are excluded from the success-rate
denominator, because scoring them as unreliability is how somebody argues for turning
the guardrail off. **(db)**
- A tool counts as declared only if the agent that called it declares it, or declares
the MCP server it came from. Per calling agent, never per estate. **(db)**
- An MCP server declared as a URL reconciles against the short name a runtime reports.
Without this every correctly-declared server is flagged, which is worse than not
checking at all. **(db)**
- Every day in a window appears in every series. A day with no runs is zero, not
missing — filled above the database, because deciding what an empty day means is a
product decision. **(db)**
- An agent that has never run returns an empty window, not a 404. Registered-this-morning
is a real state and exactly the one somebody is most likely to be checking on. **(db)**
- No run, tool call or cost figure can carry a prompt, a completion or a tool argument.
`error_kind` is a bounded classification; there is no free-text field to put model
output in. **(db)**
- Money crosses the API only as an integer count of millionths of a dollar. Summing
floating-point money over a month gives a total that depends on the order of summation.
- A percentage shown to a user is bounded and unit-free. The estate service-level figure
counts service levels meeting their target rather than averaging measurements in
different units, which is what produced a reported 1173.1%.
- Observe sanitizes trace/log envelopes before the first object-store write; replaying
the same source digest does not write a second object.
- Protected prompt, output, state and tool content is represented by a digest/reference
in normal query responses and is decrypted only through an audited payload access path.
- A failed child observation cannot close its parent execution. Root completion,
out-of-order lifecycle events, retries and replay lineage reduce deterministically.
- The Operations projection contains correlation, timing, status and aggregate usage
only; content fields cannot cross that service boundary.
- Observe query SQL binds every filter as a parameter and request transactions bind both
organization and project context. Worker access is an explicit transaction-local mode.
- Retention does not delete a shared payload object while another live reference or a
legal hold protects it; air-gap mode rejects external projection endpoints.
- A keyset cursor is opaque, survives microsecond precision, and a malformed one is a 400
rather than a silent restart at page one. A caller asking for page nine hundred must not
be handed page one with no way to tell.
- A page reports "there is more" from an over-fetched probe row that is never returned, and
the cursor it hands out is the last row the caller actually saw. An exactly-full page with
no probe row is terminal, so the console cannot show a "load more" that returns nothing.
- Rows written in one statement share a timestamp, and the trail still pages through them
without looping or skipping. The id tiebreaker is what makes this work, and a batch insert
is how the tie arises in production. **(db, unrun)**
- A permission held at account scope subsumes every narrower scope; a permission held at a
narrow scope does not imply account scope. The asymmetry is deliberate and is why `allows`
cannot be a set-membership test.
- A member with no grant can sign in and do nothing. An invite is not an identity and
confers no permission by itself. **(db, unrun)**
- A role cannot be defined with a permission outside the closed set, and every permission
seeded by migration `0017`'s built-in roles is in that set. A typo would otherwise produce
a role that looks right in the console and grants nothing.
- Roles are granted to members and teams only. A workload gets capability grants; the human
and machine permission models answer different questions and must not merge.
- An account-scoped grant carries no scope id and a narrow-scoped grant requires one, at
both the schema and the column. An ambiguous scope is one the enforcement path has to
guess about. **(db, unrun)**
- A grant that has expired stops permitting immediately, without waiting for the sweep. If
the read path trusted `revoked_at` alone, lapsed elevation would keep working for as long
as the worker was behind. **(db, unrun)**
- Two live grants of the same privilege to the same subject at the same scope are refused;
revoking frees the slot. Duplicates make revocation a guessing game — remove one, the other
still permits, and the trail says the privilege was taken away. **(db, unrun)**
- A requester cannot decide their own elevation request, and an approver can shorten the
requested duration but never lengthen it. **(db, unrun)**
- A request cannot be decided twice, so two approvers clicking at once produce one grant.
**(db, unrun)**
- A capability digest covers name, kind, input-schema digest and all four declared
annotation hints, and is independent of the order the server returned them in. A reworded
title is not drift — treating cosmetic edits as drift trains reviewers to dismiss the
banner.
- An undeclared annotation is not the same as one declared false. "The server did not say"
and "the server said no" are different claims, and only the first is grounds for asking.
- A registered MCP server denies every call until a snapshot is approved *and* granted.
Registration is an intent to govern; approval says the tools were reviewed; neither is a
permission. **(db, unrun)**
- Approving a new snapshot does not widen a grant pinned to the old one. Without pinning,
approval hands every existing grant whatever tools the server has since added — the
rug-pull the registry exists to stop. **(db, unrun)**
- Re-discovering an unchanged server is not drift and does not add a snapshot row. One row
per distinct capability set is what keeps the table bounded under continuous discovery.
**(db, unrun)**
- A server with no observation is unknown, not drifted. Conflating them puts every newly
registered server in the drift queue, which is how the queue stops meaning anything.
**(db, unrun)**
- An approved snapshot cannot be rewritten and an approval cannot be reattributed, but a
reviewer can still record a verdict on a frozen snapshot. What the server *said* is
evidence; what a human *concluded* is an opinion that may be corrected, and a trigger
written too broadly would make review impossible while looking like the feature working.
**(db, unrun)**
- Quarantine denies every call for a server without unpicking its grants, and releasing one
with nothing approved lands in review rather than approved. Claiming approved while every
call is denied is the hardest kind of outage to diagnose. **(db, unrun)**
- A security audit event cannot be updated or deleted, and lands in a month partition
rather than the default one. Retention is a partition drop; a row-level delete is also the
obvious way to remove the one event somebody did not want seen. **(db, unrun)**
- An audit record carries no caller-supplied timestamp. The database stamps `occurred_at`,
which is the partition key — accepting one from the caller is how rows get written into
last March.
- The audit `category` vocabulary is single-sourced across the Pydantic enum and the
`0017` CHECK constraint, and the two are asserted to agree. They had already drifted, and
the symptom was one subsystem's history silently never landing. **(db, unrun)** for the
constraint biting; the agreement itself is checked above the database.
- `detail` on an audit event holds flat scalars within a bounded key count, value length and
total size, and the database bound is slacker than the API's so a rejection is always a 422
naming the field. There is no field on the trail that a prompt, completion or tool argument
fits in. **(db, unrun)**
- No column on `provider_connections`, `connection_secret_versions`, `mcp_servers`,
`members` or `member_identities` is named or typed like secret storage. The structural
check matters more than any single column: it fails when somebody adds a plausible
`api_key` text field, which is how a control plane becomes a credential store one migration
at a time. **(db, unrun)**
- A secret version stores a 32-byte fingerprint and a reference, never material, and version
numbers are unique per connection. **(db, unrun)**
- A member's email is unique per account case-insensitively, and not unique globally. Two
customers can employ the same consultant; a global index refuses the second account's
joiner for a reason nobody in that account can see. **(db, unrun)**
- An IdP subject binds to at most one live member, and revoking a binding frees the subject
to be rebound. A subject live in two places makes "who did this" depend on write ordering.
**(db, unrun)**
- Built-in roles are reference rows: `builtin = (org_id IS NULL)`, readable by every
account, writable by none, and a tenant role of the same key shadows rather than replaces
one. A built-in whose meaning differs per customer is unsupportable. **(db, unrun)**
- An MCP server slug, like a customer slug, is unique per account and not globally. An
unscoped lookup would resolve one customer's tool call against another's server.
**(db, unrun)**
- A personal Platform Key cannot bind to a member from another account, and successful
verification returns the bound member so model and MCP enforcement cannot lose human
attribution between issuance and use. **(db)**
- Secret detection runs before model or MCP upstream dispatch over both raw request bytes
and decoded JSON values; JSON escaping is not a bypass, and findings contain classifications
only, never the matched value.
- Gateway audit export prefers the verified member as actor, extracts only the trace id
from `traceparent`, and requeues a failed batch without blocking the model request.

**F1 ledger and runtime identity (session 36).** Eleven invariants. The five marked
**(db, unrun)** live in `tests/sql/invariants.sql` §15–§23 and have **never executed**,
because no PostgreSQL was reachable; the six above the database run in
`tests/unit/test_agent_actions.py` (52 cases).

- `inv_ledger_append_only` — an `UPDATE` or `DELETE` on `agent_actions` is refused by
  trigger, including through the partition directly, and including a correction. A ledger
  that can be edited answers no question worth asking. **(db, unrun)**
- `inv_human_root` — no instance, and no action, without a `human_member_id`. It is a NOT
  NULL rather than a validation, because the ledger is reachable by backfill as well as by
  HTTP, and an action nobody can be asked about is not evidence. `agent_id` is nullable in
  the same breath and on purpose: an action by an *unregistered* agent is a shadow-agent
  discovery, which is one of the things the ledger exists to find. **(db, unrun)**
- `inv_delegation_attenuation` — a child's `granted_capability_selectors` is a subset of
  its parent's, and its depth is the parent's plus one, bounded at 8. Enforced by trigger
  because it is a claim about two rows, which a CHECK cannot see (threat model AP-6).
  **(db, unrun)**
- `inv_taint_monotonic` — `tainted → clean` is refused. Not a state transition; the
  erasure of a security fact. A clean context window is a new session row. **(db, unrun)**
- `inv_idempotent_ingest` — the same `(org_id, event_id)` cannot be accepted twice, proven
  on `agent_action_receipts` rather than on the ledger. The receipt table is unpartitioned
  for exactly this reason: a unique constraint on a partitioned table must include the
  partition key, and `UNIQUE (org_id, event_id, occurred_at)` would accept a retry whose
  timestamp had been corrected in flight. **(db, unrun)**
- `inv_grade_is_mandatory` — `enforcement_grade` is NOT NULL, `unknown` is a permitted
  value, and `effective_enforcement_grade()` maps it to `E` in SQL while
  `ActionDecision.effective_grade` does the same in Python. An enforcing outcome — deny,
  quarantine, mask, tokenize, route_internal, rate_limit — at effective grade E is refused
  as a contradiction: E means not covered, so nothing can have intervened. Grade D is
  allowed, because a vendor control that denied something before we heard about it is a real
  denial we did not perform, and the grade already says so. **(db, unrun)** for the
  constraint; the refusal itself is checked above the database.
- `inv_no_content_columns` — no column on `agent_actions` and no field on the envelope is
  named or typed like content. Asserted structurally in both directions: a substring sweep
  over the ORM columns and the Pydantic fields for `prompt`, `completion`, `stdout`,
  `payload`, `body`, `content`, `argv`, `command`, `text`, `message` and `path`, with the
  digest and facet columns named as the permitted exceptions. It fails when somebody adds a
  plausible `command_line` field, which is how a content-free ledger stops being one, one
  well-meaning commit at a time.
- `inv_extra_forbid_is_the_privacy_control` — every model in `aap.action.v1` sets
  `extra="forbid"`, so a collector sending `prompt`, `completion` or a raw argv array gets a
  422 naming the field. Dropping unknown keys silently would be safe for storage and useless
  as an answer to "prove you don't store our code", because nobody can see a field that was
  quietly discarded.
- `inv_facet_allow_list_agrees` — the Pydantic facet allow-list and
  `agent_action_facets_valid()` in `0024` name the same keys, and the Python bounds are
  *tighter* than the database's in the same direction. Pydantic counts characters and
  `pg_column_size` measures jsonb's binary layout, so equal numbers would make some records
  fail inside Postgres after passing validation — a constraint violation from the middle of
  a batch instead of a 422 that names the field. Same reasoning as `0017`'s `detail` check.
- `inv_vocabularies_agree` — every enum in `app/domains/agent_actions/schemas.py` is read
  back out of the migration's CHECK constraints by regex and asserted equal: capability
  kinds, outcomes, grades, resource and data classes, risk signals, taint states, harnesses,
  mutation kinds. Two vocabularies for one fact is D-057 exactly, where four of seven audit
  categories would have failed at INSERT while the trail looked healthy. The `harness` list
  is checked across `0023` and `0024` too, so a fleet view and a ledger view cannot come to
  disagree about how many harnesses the estate runs.
- `inv_single_alembic_head` — `alembic heads` returns exactly one revision. Trivial to
  assert, and the thing most likely to break when two sessions write migrations in
  parallel, which is how this session and F2 ran.

Three structural checks were added to `tests/integration/test_model_drift.py` alongside
them, all **(db, unrun)**: every migrated base table has an ORM model (with the exemptions
named and their reasons given, so a forgotten model cannot hide among them), primary keys
agree — the ledger's composite `(id, occurred_at)` is the case that matters, since Postgres
requires the partition key in the primary key — and no NOT NULL column without a server
default is absent from its model. The first of these is the one that would have caught
`app/db/models/auth.py` never being exported.



---



## Session log

Newest first. One entry per session, three lines maximum.

### Session 37 — 2026-10-09 (public repository)

Removed internal MCP servers and the hosts, directory users, and sample passwords that
lived with them. Adapter and Compose now mount only `examples/mcp/demo_server.py`. Public
docs and harness marks added. No migration. Not run against Docker or a browser.

### Session 36 — 2026-09-22 (F1 — ledger and runtime-identity schema)

`0023` runtime identity (mandatory human root, monotonic taint, trigger-enforced delegation
attenuation) and `0024` the partitioned append-only content-free `agent_actions` ledger plus
an unpartitioned receipt table for idempotency; thin ORM models, typed `aap.action.v1`,
52 unit tests, nine SQL invariant sections. D-078–D-080. Three defects found by writing it:
`agents`/`agent_versions` never had the `UNIQUE (org_id, id)` the ORM declares, `auth.py`
models were never exported so `0022` was invisible to the drift test, and a generated grade
column is impossible on a partition built with `CREATE TABLE (LIKE ...)`. 1152 passed / 177
skipped, lint clean, mypy clean on F1's files (10 pre-existing errors elsewhere, untouched);
**no PostgreSQL**, so both revisions are written-not-applied and every SQL invariant unrun.

### Session 35 — 2026-09-22 (F2 — UI structure: navigation, ledger home, grades)

Server-authored navigation with `product_mode`/capability flags, `Rail.tsx` and `TopBar.tsx`
deleted, ledger home with four honestly-empty slots behind `HomeRoute`, `EnforcementGrade`
chip, `DataBoundary` for all four states with the project as a filter not a gate. D-074–D-077.
1,151 unit tests (25 new on navigation), `check:api`, `check:runtime`, typecheck, lint and
`vite build` all pass; **no browser and no database were involved**, so none of it is
certified beyond source and types. Found stale `openapi.json` breaking `SessionSummary` —
D-049's first real instance. No migration written; F1's `0023`/`0024` status corrected only.

### Session 34 — 2026-09-22 (F0 — console contract: login, session, errors)

Server-side sessions, `/v1/auth/config`, `/v1/session/bootstrap` and a reason-coded error
envelope; `AAP_DEV_AUTH_BYPASS` and `Bearer dev.<email>` deleted for a `development`
provider row. Unit suite (1099 at F0 close) and `check:runtime` pass; three defects found.
No Docker or PostgreSQL on this machine, so `0022` stays **written, not applied**,
integration and Playwright unrun, and `tests/smoke/` is knowingly left 401-ing.

### Session 33 — 2026-09-22 (development prompts, schema/UI blueprint; no product code)
Regressed all 23 prompt files against design 12–17, real Alembic head `0022` and the existing gateway/MCP/Observe/UI implementation. Replaced the executable sequence with F0 → F1 → F2 → M1 → M3 → M4 → M2 → M5 → V1 → packaging; added F1 schema ownership, corrected table/API/migration collisions, and marked P0–P9 historical.
Recorded D-073 and resolved Q-L/Q-M to read-only ledger, Claude Code first and Cursor before demo; Q-026 retains Q-N/Q-P/Q-Q at their real gates. Updated migration doc, roadmap and new `16-mvp-schema-and-ui` diagram; all 16 diagrams build and validate with zero layout defects.
No migration or product module changed. `0023`/`0024` are specified only; `0019`–`0022` application status was not re-verified. Next slice is F0, with F1 allowed in parallel.

### Session 32 — 2026-09-22 (research pass and design revision; no product code)
Added `design/12`–`18` (thesis, threat model, identity/authorization, capability governance, market, conclusions, 108-source bibliography), four generated diagrams (`12`–`15`, all passing `validate.mjs`), and amendment headers on `01`–`08` and `11`. Recorded D-066…D-072: the capability replaces MCP as the top-level object, the MVP becomes a read-only graded action ledger, Cedar is the policy engine, the credential broker replaces the token vault, and the identity chain gains version/instance/session/task.
Two assumptions were falsified: both enforcement points were absent from the path of the 25 April 2026 reference incident (`fs.read → shell.exec → net.http`), and Cursor prompt DLP is unsupportable because Cursor's backend resolves model traffic `[B-41]`. Also removed a hardcoded employer domain from three dev-bypass paths — no module state changed.
New blocking open question Q-025 (Q-L … Q-Q); Q-024 partially closed (D-A, D-D, D-G). No migration written or applied; every new entity is specified only. The phase prompts are now stale and must be regenerated from `17` §7.

### Session 31 — 2026-09-21 (no work on this project; owner paused it)
Owner set this product idea aside after concluding the agent-governance market is closed to a solo part-time founder, and redirected the session to career work (resume, GitHub, LinkedIn, an open-source Java debugger, interview prep) outside this repository.
No module status, migration, decision or invariant changed here. `design/` and the phase prompts remain as Session 30 left them, unbuilt and awaiting D-A…D-G.

### Session 30 — 2026-09-19 (AI control plane design set; planning only)
Wrote `design/`: 11 specifications, 11 generated Excalidraw sketches with SVG/PNG previews, a layout validator reporting zero defects, and 10 paste-ready phase prompts; rewrote `docs/architecture/AI_CONTROL_PLANE_PLAN.md` as the approval summary.
Settled tenancy/DL hierarchy, per-account auth providers, permission vs visibility, attested residency, ordered MCP checks, DLP matrix, ClickHouse pipeline and the expand/contract migration. Recorded D-064 and D-065 (MCP moves from phase 1 to phase 5); no code or module status changed; D-A…D-G await the owner.

### Session 29 — 2026-09-18 (identity-owned tenancy and employee onboarding)
Removed browser-owned org selection; added invitation-gated Entra activation, company-labelled profile and employee/team onboarding UI. 21 PostgreSQL tests and web build pass.
Registered, discovered and approved Nexus/Bitbucket MCP snapshots (38 tools); adapter and affected API routes are healthy.

### Session 28 — 2026-09-18 (live Activity, member-bound gateways, data protection)
Removed runtime Nexus fixtures; split Activity into live exact-match routes; added profile, live MCP/model setup, hierarchy and Nexus security audit. Applied `0018`; member attribution now crosses Platform Keys, MCP usage/OTel and signed gateway bindings; model/MCP secret scans cover decoded JSON and gateway decisions export to durable audit. API 33, Postgres 11, MCP adapter 6, web lint/build pass; Docker stopped before final Go rerun/image deployment.

### Session 27 — 2026-09-18 (Nexus Activity/MCP, Entra login, MCP onboard)
Replaced Observe Activity + execution detail and MCP registry/detail with Nexus glass UI; People now has hierarchy/productivity/directory. Added generic OIDC PKCE login (development localhost session); the public tree ships only the synthetic demo MCP. Execution graph still fixture-backed; Q-013 issuer/`OrgGate` replacement still open.

### Session 26 — 2026-09-18 (Nexus shell and database certification)
Deployed the Nexus six-destination glass shell plus live Control Center and Platform Keys surfaces; web lint/type/build and 137 API-path checks pass. Applied `0017`; real PostgreSQL tests found and fixed 14 missing ORM UUID server defaults and one async MCP rediscovery refresh defect, then **54/54 integration tests passed**.

### Session 25 — 2026-09-18 (account, access, credentials, MCP registry, audit)
Implemented the directed half of the redesign: migration `0017` (16 tables, month-partitioned append-only audit, 8 seeded roles), five domains with an RBAC engine and keyset pagination, and seven console screens on a new dual-theme design system. 72 unit tests pass; **`0017` was never applied and 54 integration tests all skipped** — no Postgres on this machine (Q-025).
Unit tests caught the audit `category` vocabulary drifting between the enum and the CHECK constraint, which would have rejected four of seven categories at INSERT (D-057).

### Session 24 — 2026-09-17 (UI approval prototype and communications HLD)
Created one self-contained interactive HTML approval prototype spanning all proposed console, profile, credential and access surfaces. Extended the existing Draw.io HLD from 14 to 17 pages with service communications, storage/state ownership and end-to-end enforcement/tracing; no product code or migration changed.

### Session 23 — 2026-09-17 (value, pricing and scale P&L)
Assessed the account/access/console redesign as a company control-plane product; drafted edition + capacity + cheap gateway-meter pricing aligned to existing offline licences. No production code, entitlement schema or migration changed.

### Session 22 — 2026-09-17 (account, access and console redesign draft)
Audited identity, tenancy, RBAC, credentials, console routes and all Sep 17 requirements; consolidated gateway adoption, MCP registry/snapshots/tool grants/enforcement, adjacent registries and enterprise controls into the tracked plan and Canvas. Corrected duplicate open-question IDs to Q-023/Q-024; no production code, dependency or migration changed.

### Session 21 — 2026-09-17 (Assurance-Native Agent Gateway draft)
Audited the Go Router, control-plane policy, Observe, MCP/A2A tracing and the September 2026 gateway market. Produced a draft that keeps Go, prioritises assurance-bound MCP enforcement and A2A mediation, and defers semantic-cache infrastructure pending measurement; no product code or migration changed.

### Session 20 — 2026-09-16 (Agent Execution Observability implementation)
Implemented Phases 2–12 across Observe, collector, Python/TypeScript SDKs and the execution/session console; added PostgreSQL/ClickHouse migrations 003–006/001–006, security/retention controls, final tracing docs and deterministic FOSS demo. Current quality suites pass (51 Observe, 36 collector, 33 Python SDK, 29 TypeScript SDK); web build/lint and local containerized demo pass. Phase 13 fresh-volume/recovery/load certification remains.

### Session 19 — 2026-09-16 (Agent Execution Observability audit)
Audited frontend, control plane, Observe/collector, SDKs, tests, APIs and Compose; added root `PLAN.md` and two architecture documents. Owner approved Observe-canonical/operations-projection, retained `aap-trace`, approved Playwright and expanded scope to first-class per-user activity. No production code or migration changed.

### Session 18 — 2026-09-15 (runtime suite deployment)
Completed typed Router/Observe/Prompt/Evaluate console flows; integrated and deployed the full Compose suite with scoped runtime bootstrap. Applied API `0016` plus Observe/Prompt/Evaluate migrations; fixed packaged SQL, ClickHouse TTL, OTLP hex IDs and worker durability. Web build/contracts, Go race suite, lint and live OTLP/BFF smoke pass; Gateway awaits a real provider route/signed snapshot.

### Session 17 — 2026-09-15 (edge OTLP collector)

Rewrote `services/collector` only: durable spool-before-ack, capture modes, Observe
forward/replay, metrics/health/readiness; dropped v0.1 evidence-event path. `ruff` /
`mypy` / 23× `pytest` green in-package; docker-compose still points at old env names.

### Session 16 — 2026-09-15 (gateway remote config)

Production-safe HTTP signed-config sync in `services/gateway` only: shared
`Store.ActivateExact`, remote poller with ETag/304, header cross-check, pinned PEM.
httptest coverage for tamper, oversize, timeout, expired, last-good; file loader regression
kept. `go test` / `-race` / `vet` clean in `golang:1.23` Docker (no local Go on PATH).

### Session 15 — 2026-09-15 (contract integrity)

The console had never been deployed: `web` served a bundle baked into its image hours
before the work, so four screens were "broken" because their routes were absent from what
nginx was serving. Underneath that, 15 of 53 request paths pointed at routes that never
existed and ~12 response types had drifted, both hidden because `src/mocks` was wrong in
the same places — deleted, 2,629 lines (D-048 to D-052). Types now generated from the
spec; `check:api` and `sweep.py` added, the latter finding a live 500 (`c.name` for
`customers.display_name`) on its first run. Also fixed a test that could only pass after
12:00 UTC. 653 passed; 78 of 85 routes 2xx, zero server errors. `tasks.md` written, HLD
gained pages 10–14.

### Session 14 — 2026-09-14

Four capabilities built in parallel by four agents: `composition` (tools, rules, skills,
subagents, configs, with declared-versus-observed reconciliation), a deterministic
plain-language review brief over the semantic changeset, `model_routing` (model catalogue,
residency resolution, emitted gateway config, drift), and probe suites with deterministic
oracles plus regulation rule-gap analysis. Console rebuilt to the owner's reference design,
light theme throughout. Found and fixed a module-level import cycle between `composition`
and `assurance`, and added a test that enforces layering from a single source of truth.
653 passed. **No descriptor version labels anywhere, by owner's instruction (D-043).**

### Session 13 — 2026-09-14 (regression fixes)

Smoke test resolves migration-seeded org; observed-graph tab lazy-loads Cytoscape; added
`test_model_drift` and fixed `control_mappings.evidence_kind` ORM type. **581 passed**;
smoke ×3; web main chunk back to ~414 kB.

### Session 12 — 2026-09-14 (design pack)

Added `docs/design/` README plus four designs: composition, interpreter, model routing,
probes/gaps. Reuses differ, materiality, engagements cross-border ladder, probe_suites.

### Session 11 — 2026-09-14 (run tracing API)

Applied `0009_run_steps`; extended `operations` with step ingest, `RunDetail`, observed
graph, seed/backfill (~100k steps), 23 new tests. **580 passed**, 4 skipped; ruff and
mypy clean. Live tracing endpoints verified; `tests.smoke` failed at org registration (not re-run to green).

### Session 10 — 2026-09-14 (console UI)

Light-theme console: tokens, Shell/Rail/TopBar, overview restyle, `RunDetailScreen` and
observed graph tab with mocks per `docs/contracts/tracing.md`. Web: tsc, eslint, vite build clean.

### Session 9 — 2026-09-14

Q-016 closed: the commit ran in dependency teardown, after the response, so a write was
readable about half the time (D-037). Found the auth invariant had been checking 1 of 47
routes since FastAPI 0.141 and passing (D-038). New `operations` domain — runs, cost,
tool and MCP usage — with migration `0008`, 35 tests, and the console rebuilt around it:
dark rail, shared window, hand-drawn charts, four new screens. Fixed a service-level
figure reported as 1173.1% (D-040) and MCP reconciliation flagging 14 correct
declarations as undeclared (D-039).

### Session 8 — 2026-09-14

Q-004 and Q-011 closed: generic OIDC replaces the forgeable `X-Org-Id`, and `0006`/`0007`
converge the cross-border constraint and add `identity_bindings`. Found two
unauthenticated endpoints, two findings-lifecycle bugs, a deprecated Starlette constant
in five routers, and that RLS is bypassed by the app's own role (Q-015). `portal` taken
from 1 test to 15, closing the customer-facing half of Q-008.

Then the console was opened properly for the first time and three things fell out of it.
The trust portal was a 500 for every client in the demo, because one engagement slug
matched five of them (D-035). The landing page called an endpoint that had never been
built, so it worked in mock mode and errored in live mode (D-036). And the navigation was
grouped under the architecture layer names from AGENTS.md, which is why none of it could
be found. The console is rebuilt around what a person came to do, every screen now says
in one sentence what it is for, and the home page answers whether anything is wrong
instead of showing four charts.

Q-016 is the one to read first: a write is only about half the time readable immediately
afterwards, because the transaction commits in dependency teardown rather than before the
response. 499 tests pass and did not catch it — they share a session, so no test in the
suite makes a second HTTP request.

### Session 7 — 2026-09-13

Five migrations applied to real Postgres 16 both ways; stack healthy; 30-check dry run and
293 tests pass. Ten defects, incl. Merkle sealing, API boot under Compose, an env alias
that let the integration suite pass having migrated nothing, and a console serving mocks.
Seed generator, Windows scripts and a live console added. Q-011 now blocks the demo path.

### Session 6 — 2026-09-13

Closed the gate/console split: `preview_release` and `create_release` now run the real
materiality engine, pinned by a test. Fixed the Merkle inclusion proof, ladder vocabulary,
a SQL injection in `graph`, and silent `None` returns in `providers/secrets.py`.
CLI made CI-safe (encoding, flag positions, `python -m`); 254 + 31 tests pass, Q-005 closed.

### Session 5 — 2026-09-13

`packages/aap-cli`: validate, diff, preview (online/offline), pack; httpx client, schema bundle, pytest with MockTransport.
Ruff/mypy/pytest clean in `aap-cli`; API package installed for `[offline]` tests only.

### Session 4 — 2026-09-13

Console feature screens: dashboard, agents (list/detail/version), releases (list/detail), evidence explorer.
Release detail implements semantic grouping, impact rail, adjudication, raw descriptor tab. `tsc --noEmit` clean; tests not run.

### Session 3 — 2026-09-13

Web console foundation: Tailwind tokens, mock API client, fixtures (40 agents, demo model-provider
release), shared components, router shell. `tsc --noEmit` clean; feature screens are placeholders.

### Session 2 — 2026-09-13

Company model: migration `0002` adds customers, contacts, engagements, service levels,
engagement-agent version pinning, frameworks with seeded ISO 42001 / NIST AI RMF / EU AI
Act controls, and control mappings. Full `customers` slice including the readiness view.
UI decided as web plus CLI (ADR `0001`). This document and its rule created. 68 tests pass.

### Session 1 — 2026-09-13

Repository scaffold. Config with deployment-mode invariants, provider abstractions for
secrets/object store/signing, offline licensing, migration `0001`, the semantic differ,
Docker Compose for dev and BYOC, Helm chart, AAP JSON Schema. 47 tests passing.