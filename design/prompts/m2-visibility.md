# M2 — Visibility, grants, and server-driven navigation

> Paste this whole file as the only prompt of a fresh session.
> Prerequisite: F0 bootstrap, F2 nav contract, M1 identity chain and M3 action list.

## Objective

Separate **permission** (can you do this?) from **visibility** (which rows do you see?).
One `visible_paths` (or current equivalent) rule intersects every list query. Navigation is
the manifest from bootstrap, not a hardcoded list of links.

## Read first

- `design/04-authorization-and-dashboards.md`
- `design/02-identity-and-onboarding.md` (org-unit tree)
- `design/03-data-model.md` §A
- Existing `app/domains/access/`, `members/`
- `design/prompts/f2-ui-structure.md` — nav groups

## Scope

**In:**

1. If `org_units` + closure still do not exist, this is the session that adds them
   in hand-written revision **`0025_org_units_visibility`**, after F1's `0023` and `0024`.
   Backfill: one root unit per organization; existing
   `teams` become `kind='team'` children. Do not fail the whole MVP on a 30×200 DL import
   — that was the old P1 gate. Gate here is: **a second unit exists and a member scoped to
   it cannot see the sibling's agents or actions.**
2. Roles already seeded in `0017` — map them to ledger needs (`security_admin`, member,
   unit admin). Do not invent a parallel RBAC. If `access_grants` must widen, use a
   separate **`0026_access_grants_visibility_widen`** revision and snapshot every member's
   effective permission set before and after. Any difference not explicitly approved,
   including a widening, aborts the migration.
3. Every new list endpoint (`agents`, `instances`, `actions` when M3 lands) intersects
   visibility on the server. Empty is not `[]` when the caller asked for a path they cannot
   see — that is `403 scope_outside_grant` with `next`.
4. Bootstrap navigation manifest matches F2 groups and the caller's permissions. A module
   they cannot use is absent, not disabled.
5. Payload reveal (prompts etc.) remains **impossible** for ledger rows — there is no
   payload. Do not add a reveal path "for later".

**Out:** Cedar (V1a), MCP grant rewrite (V1c), ClickHouse, DL CSV import at 30×200 scale
unless it is cheap on the existing bulk path.

Do not drop `teams` or `team_members` in this slice. Dual-read/backfill first; destructive
contract cleanup happens only after a full phase of proven reads.

## UI

- People / Access screens already exist. Extend Access to show org-unit scope on a grant.
- Deep link into a hidden module → "request access" page naming an approver if F0 `next`
  is available; otherwise a reason-coded 403 page.

## Invariants

| Name | Assertion |
|---|---|
| `inv_scope_outside_is_403` | Requesting a sibling unit is 403, never empty 200 |
| `inv_member_cannot_see_other_member_actions` | When M3 tests exist, keep this; if actions table empty, test on agents |
| `inv_nav_omits_forbidden` | Bootstrap manifest does not contain a path the caller cannot GET |
| `inv_list_intersects_visibility` | Direct repository call without org+visibility is not used from routers |
| `inv_grant_backfill_equivalent` | Effective permissions are identical before/after `0026` |
| `inv_org_unit_backfill_idempotent` | Re-running the team backfill creates no duplicate units or memberships |

## Gate

- [ ] Two org units, two members, proven both ways with API tests.
- [ ] Ledger-mode nav from bootstrap, not from `NAVIGATION` constants alone.
- [ ] `PROJECT_STATE.md` updated.

## Do not

- Do not implement Cedar here.
- Do not change MCP grant semantics.
