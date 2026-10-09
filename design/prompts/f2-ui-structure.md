# F2 — UI structure, existing usage, and improvements

> Paste this whole file as the only prompt of a fresh session.
> Can overlap F1 (schema) because this session must not add product screens that need new
> tables. It **must** close before M5 (ledger console) and should close before M1 screens.

## Objective

Give the console one information architecture that matches the product we are actually
building — an agent action ledger — by **reusing** the existing UI system, not inventing a
second one. After this session a developer can add a ledger screen without choosing between
three shells, two navs, and four error components.

## Read first

- `design/prompts/README.md`
- `design/09-frontend-and-api-contract.md` — five rules
- `design/04-authorization-and-dashboards.md` amendment (every number carries a grade)
- `design/12-strategic-thesis.md` §5 — grades A–E
- Current UI (read these, do not redesign from memory):
  - `services/web/src/App.tsx` — route table
  - `services/web/src/components/Shell.tsx` — **the live nav** (Nexus / lucide)
  - `services/web/src/components/Rail.tsx` — orphaned legacy nav; verify it is not mounted
  - `services/web/src/components/NexusUI.tsx`, `Panel.tsx`, `Stat.tsx`, `ErrorState.tsx`,
    `Skeleton.tsx`, `TopBar.tsx`
  - `services/web/src/features/observe/*` — closest product UI to the ledger
  - `services/web/src/features/dashboard/HomeScreen.tsx` — accreditation-era overview
  - `services/web/src/features/suite/SuiteProjectProvider.tsx`
  - `services/web/src/lib/suiteModules.ts`

## What exists today (inventory — treat as fact)

Two products are stacked in one app:

1. **Assurance / accreditation console** — `/agents`, `/releases`, `/accreditations`,
   `/customers`, `/engagements`, `/findings`, `/evidence`, `/graph`, `/policy`, `/sla`.
2. **Runtime suite** — `/observe`, `/router`, `/prompt`, `/evaluate`, gated by
   `GET /v1/modules`.
3. **Admin** — `/admin/people|access|connections|mcp|audit`, `/profile`, `/platform-keys`,
   `/control`, `/model-routing`.

Two navigation implementations remain in source (`Shell.tsx` live, `Rail.tsx` orphaned) and
disagree about labels, grouping and which product is primary. Observe still sits behind `ModuleGate` + `SuiteProjectProvider`,
so a first login can render a wall instead of activity. `ErrorState` defaults to the title
"Something went wrong" and has no reason code / `next` action. `HomeScreen` is ordered around
approvals and framework bars — the opposite of the MVP (coverage, dark population, credential
exposure). `Shell.tsx` barrel-imports `lucide-react`.

## Scope

**In — structure and contract, not new product features:**

1. **One navigation source.** `Shell.tsx` is canonical. Stop rendering `Rail.tsx` from any
   live layout. Keep the file only if a test still needs it; otherwise delete the import
   path. Navigation groups for MVP default:

   ```
   Home                         /
   Ledger                       /observe          (reuse Observe routes)
     Actions                    /observe/executions
     Sessions                   /observe/sessions
     Live                       /observe/live
   Agents                       /agents
   Discovery                    /discovery        (placeholder route + empty state only)
   Control
     MCP                        /admin/mcp
     Platform Keys              /platform-keys
     Connections                /admin/connections
   Admin
     People                     /admin/people
     Access                     /admin/access
     Audit                      /admin/audit
     Profile                    /profile
   ```

   Accreditation, customers, engagements, prompt, evaluate, router, SLA, graph stay
   **reachable by URL** and appear in nav only when bootstrap `capability_flags` say so
   (default **off** for a fresh account). Do not delete those screens.

2. **Server-driven nav.** Bootstrap (F0) returns the manifest. If F0 is not done, add a
   typed `nav` module that reads flags from `/v1/modules` plus a new `product_mode`:
   `ledger` (default) | `assurance`. Do not hardcode the ledger IA in five files.

3. **`<DataBoundary>`** in `components/DataBoundary.tsx`. Props: query result, empty
   description, children. Renders:
   - loading → existing `Skeleton` / `TableSkeleton` shaped like the result
   - empty → what the screen is for + one action
   - error → `reason`, `message`, `next` as a button, `request_id`
   - data → children, with `freshness_at` if present

   Replace `ErrorState` usages on the screens you touch. Keep `ErrorState` as a leaf that
   `DataBoundary` may call, but it must accept `reason` and `next`.

4. **Project is a filter.** `SuiteProjectProvider` never blocks Observe. No project → all
   projects in scope.

5. **URL is the state.** Tabs and filters via `useSearchParams`. Active nav from pathname
   (`end` / `matches`), never local `activeTab` state. Fix any tab that highlights more
   than one item.

6. **Home becomes a ledger home shell** (layout only): four slots with empty/loading
   states — coverage by grade, recent high-risk actions, unregistered collectors, credential
   exposures. Wire them to **existing** APIs if a number already exists; otherwise render
   the purposeful empty ("ingest is M3"). Do not fake counts.

7. **Reuse, do not restyle.** Use `NexusCard`, `NexusBadge`, `Panel`, `Stat`, Observe table
   density, existing colour tokens. No new CSS framework. No new icon library.

   Reuse these existing structures deliberately:
   - Observe list/detail, timeline and graph for ledger drill-down
   - admin People, Access, Connections, MCP and Audit screens
   - `Pagination`, `RelativeTime`, `StateBadge`, `WindowDaysSelect`
   - existing same-origin `/v1` client and typed OpenAPI contract
   - existing Nexus shell and theme tokens as the primary visual language

   Do not migrate every assurance-era `Panel` screen. New ledger surfaces use Nexus; old
   screens remain reachable and are improved only when a later slice touches them.

8. **Lucide.** Stop barrel-importing. Either `optimizePackageImports` in the bundler config
   or per-icon imports. Direct imports preferred.

9. **Grade chip.** One `<EnforcementGrade grade="A"|"B"|"C"|"D"|"E"|"unknown" />` used
   everywhere a number or a row is shown. `unknown` renders as E visually, labelled
   "ungraded". A count without a grade is a lint/test failure on ledger screens.

**Out:** new ingest, new tables, Cedar, MCP behaviour changes, DLP, rewriting Observe's
timeline/graph (reuse as-is), Playwright covering every legacy screen.

## API and route contract

- Keep every existing URL working; add redirects only when there is one canonical target.
- Regenerate `openapi.json` and `api/schema.d.ts` only if F0 changed the bootstrap contract.
- `App.tsx` remains the route owner; `Shell.tsx` remains the chrome owner.
- No screen calls `/v1/members/me` or a second identity endpoint after bootstrap.
- Home slots consume typed nullable data; "not implemented yet" is a purposeful empty
  state, never a fake zero.

## Improvements that are in scope because they unblock development

| Problem | Fix |
|---|---|
| Two navs | One (`Shell`) |
| Observe behind a project wall | Filter |
| Generic error title | Reason + next |
| Home is the old product | Ledger shell with empty states |
| Lucide barrel | Direct imports |
| Deep links `/sessions/:id` already redirect into Observe | Keep |
| `/runs` vs `/observe/executions` | Prefer Observe; `/runs` redirects or stays for assurance mode |

## Invariants

| Name | Assertion |
|---|---|
| `inv_single_nav_source` | No live layout imports `Rail.tsx` |
| `inv_data_boundary_exists` | `DataBoundary` is used on Home and Observe layout |
| `inv_observe_without_project` | Observe overview renders with no project selected |
| `inv_grade_chip` | `EnforcementGrade` exists and `unknown` labels as ungraded |
| `inv_no_lucide_barrel` | `from "lucide-react"` with multiple named icons is gone from `Shell.tsx` |
| `inv_existing_urls_survive` | Existing assurance/admin deep links still resolve |
| `inv_one_identity_request` | Shell and touched screens consume bootstrap, not separate identity calls |

## Gate

- [ ] Fresh login in ledger mode shows Home + Observe + Agents + Admin, not Clients /
      Contracts / Approvals as the primary story.
- [ ] Observe loads with zero projects.
- [ ] A forced API 403 on Home shows a reason code, not only "Something went wrong".
- [ ] Accreditation routes still work if you type the URL.
- [ ] `npm run check:api`, `npm run check:runtime`, typecheck and production build pass.
- [ ] The UI audit script covers Home, Actions placeholder, Agents, Discovery and Admin
      with zero console errors.
- [ ] `PROJECT_STATE.md` updated.

## Do not

- Do not add a third component library.
- Do not rebuild Observe's execution graph.
- Do not hide `/admin/mcp` — V1 needs it, and M4 discovery will link to it.
- Do not invent dummy coverage percentages.
