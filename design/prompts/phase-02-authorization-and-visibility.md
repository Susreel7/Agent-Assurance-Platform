# Phase 2 — Roles, scoped grants, the visibility rule, persona dashboards

> **HISTORICAL — DO NOT EXECUTE.** Superseded by
> [`m2-visibility.md`](m2-visibility.md) and V1 policy. It assumes a pre-`0017` RBAC model
> and unsafe migration numbering.

> Paste this whole file as the only prompt of a fresh session.

## Objective

Give every caller exactly the permissions and exactly the visibility they should have, through
one function that every read uses, and prove it with tests in both directions. This is the
highest-risk phase in the plan: a mistake here is either a lockout or a data leak.

## Prerequisite

Phase 1's gate: the org-unit tree, memberships, managers and directory sync are live.

## Read first

- `design/04-authorization-and-dashboards.md` — all of it
- `design/03-data-model.md` §B
- `design/10-migration.md` — revision 0027 and "The one risky migration"

## Scope

**In:** permission catalogue; built-in roles; `access_grants` widened to the full subject/scope
matrix with `subtree` and `environments`; group-rule-driven grants; the `visible_paths` function
and its cache; `payload:reveal` plus approvals; access requests; separation-of-duty checks; the
five persona dashboards reading real aggregates from existing data; the access-management UI.

**Out:** gateways, DLP, ClickHouse. Dashboards in this phase read from what exists today; P7
moves them to rollups without changing their contracts.

## Database (revision 0027, then 0032a)

```
0027  roles: permissions[], assignable_scopes[], separation_of_duty, builtin, account_id nullable
      access_grants: subject_kind widened (member|org_unit|directory_group|service_identity|agent),
                     scope_kind widened (account|org_unit|project|resource),
                     subtree bool, environments text[], source, granted_reason
      seed the nine built-in roles from design/04
      backfill: team-scoped grants → org_unit grants with subtree=true
0032a access_requests rework; approvals table (kinds: payload_reveal, policy_change now;
      tool_call and model_request land in P5/P3 and must not need a schema change)
      member_visibility materialised view + refresh triggers
```

**Migration protocol for 0027, mandatory.** Before: snapshot every member's effective permission
set into a temp table. Migrate. After: recompute and diff. Any difference — including a widening
— aborts the deployment. Only then drop the temp table. Put this in the migration itself, not in
a runbook.

## The visibility function

Implement once, in one module, used by every read:

```python
def visible_paths(session) -> VisibilityScope:
    """{self} ∪ {granted org-unit subtrees} ∪ {'/'} if account-scoped activity:read_all."""

def narrow(requested_scope: str | None, scope: VisibilityScope) -> str | list[str]:
    """Intersect a caller-supplied scope with what they may see.
    Empty intersection raises ScopeOutsideGrant — never returns an empty filter."""
```

Rules that must be enforced by code, not by convention:

- Every activity, cost, risk and graph endpoint calls `narrow()`. Add a test that walks the route
  table and fails if a route declares `activity:read` without calling it.
- No endpoint accepts `member_id` from the caller without intersecting it.
- An empty intersection is `403 scope_outside_grant` with the visible units in `detail` — never
  an empty result set, which would read as "no AI usage".
- The scope is computed at bootstrap, cached with the session, invalidated on grant, membership
  or org change. Never recomputed per row.
- Custom roles may only be a subset of an existing role and may never include `access:write` at
  account scope.

## Backend surface

```
GET   /v1/access/roles                               built-ins + custom, with permissions
POST  /v1/access/roles                               custom role, subset-validated
GET   /v1/access/grants?subject=&scope=&role=        with "why" — which rule or person granted it
POST  /v1/access/grants                              reason required; SoD checked
DELETE/v1/access/grants/{id}                         revoke with reason
GET   /v1/access/effective?subject=                  resolved permissions + the grant that caused each
POST  /v1/access/requests                            request a role at a scope, with justification
POST  /v1/access/requests/{id}/decide                approve or deny, with a note
GET   /v1/access/approvals?state=                    runtime approvals queue
POST  /v1/access/approvals/{id}/decide
POST  /v1/activity/payload-reveal                    request; returns an approval id
GET   /v1/insights/usage?group_by=&window=&scope=    the single aggregate endpoint
GET   /v1/insights/denials · /adoption · /cost       same scoping, same envelope
```

`/v1/access/effective` is the endpoint that makes this system auditable — it must explain *why*,
naming the grant, the rule or the group that produced each permission. Build it now, not later;
it is also the fastest way to debug the rest of the phase.

## Frontend

- **Access** screen: grants table with subject, role, scope, subtree, environments, source,
  expiry; filters; bulk revoke; a "why can this person do this" drawer.
- **Role** detail: permissions, where assignable, who holds it, separation-of-duty warnings.
- **Requests**: mine and to-decide, with justification and decision notes.
- **Five dashboards** exactly as specified in `design/04`: member, DL admin/manager, security
  admin, platform/finance, auditor. Each reads `/v1/insights/*`, renders `freshness_at`, and
  renders `withheld_fields` as a lock with a reason rather than a blank cell.
- Navigation manifest now reflects real permissions, so a persona sees only their modules.

## Invariants to add

| Name | Assertion |
|---|---|
| `inv_scope_narrowed_everywhere` | Every route requiring `activity:read` calls `narrow()` |
| `inv_no_empty_scope_fallback` | An out-of-scope request returns 403, never empty data |
| `inv_dl_admin_subtree_only` | A DL admin sees their subtree and nothing outside it |
| `inv_custom_role_subset` | A custom role cannot exceed its parent's permissions, nor hold account `access:write` |
| `inv_sod_enforced` | The grantor of a request cannot decide it |
| `inv_payload_requires_approval` | A payload field is withheld without both `payload:reveal` and a live approval |
| `inv_grant_migration_neutral` | Revision 0027 changes no member's effective permissions |

## Test plan

1. Matrix test: for each of the nine roles × every route, assert allowed or `module_forbidden`.
   Generate it from the route table so a new route cannot be forgotten.
2. Visibility test: a fixture with two DLs under one BU; assert the DL admin sees exactly the 212
   members, the BU manager 397, the member 1, and the neighbouring DL returns 403.
3. Inheritance test: a grant on a parent unit is effective for a grandchild; revoking it removes
   effectiveness immediately after invalidation.
4. Group-rule test: adding somebody to the Cursor-Admins group in the directory produces a
   `dl_admin` grant; removing them revokes it.
5. Payload test: security admin without approval gets `withheld_fields`; with an approval, the
   field resolves, and the reveal is in the audit log with the approver.
6. Cache test: revoking a grant invalidates the cached scope within one bootstrap cycle, and the
   next request is 403.
7. Playwright: the five personas each see their own dashboard and no others in the navigation.

## Acceptance criteria (the gate)

- [ ] A DL admin sees exactly their subtree; a neighbouring unit returns `scope_outside_grant` with their visible units listed.
- [ ] `/v1/access/effective` explains every permission with the grant that produced it.
- [ ] Revision 0027 provably changed no effective permission.
- [ ] Payload reveal requires both a permission and an approval, and the reveal is audited.
- [ ] Each of the five dashboards renders for its persona, with freshness and withheld-field handling.
- [ ] The role × route matrix test passes with no route unlisted.

## Deliverables

Revisions 0027 and 0032a with the diff-guard; `access` domain rewritten; the visibility module;
route-table test generator; five dashboards; access-management screens; seven invariant tests;
updated `PROJECT_STATE.md`.

## Do not

- Do not add a "superuser" or "impersonate" path. If support needs one later it is a designed,
  time-boxed, two-person, heavily audited feature — not a flag added during this phase.
- Do not let a dashboard query bypass `narrow()` "because it is only aggregates". Aggregates leak.
- Do not widen a built-in role to make a test pass.
