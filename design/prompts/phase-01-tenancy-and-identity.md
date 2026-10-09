# Phase 1 — Tenancy, org units, directory sync and onboarding

> **HISTORICAL — DO NOT EXECUTE.** Superseded by F1, M1 and M2 in
> [`README.md`](README.md). Its migration IDs collide with the real chain and parts of its
> identity/access model already exist in revisions `0017`–`0022`.

> Paste this whole file as the only prompt of a fresh session.

## Objective

Build the identity foundation the whole product hangs from: accounts with deployment modes, one
org-unit tree that models business units, teams **and distribution lists**, membership and
manager relationships, directory synchronisation, all five onboarding modes, and exactly one
auditable way an account gets its first administrator.

Concrete shape to fit: one account, tens of DLs, hundreds of people in the largest DL, one admin per DL, a
few admins above all DLs.

## Prerequisite

Phase 0's gate is demonstrated: server-side session, single bootstrap, reason-coded errors.

## Read first

- `design/02-identity-and-onboarding.md` — all of it
- `design/03-data-model.md` §A
- `design/10-migration.md` — revisions 0024–0028 and "Identity data migration, concretely"
- `design/diagrams/03-hierarchy-and-visibility.excalidraw`

## Scope

**In:** `org_units` + closure + managers; `member_org_units`; `members` extensions;
`directory_groups` + `group_org_unit_rules`; invitations rework; SCIM 2.0 inbound; directory
pull (Graph and LDAP); bulk CSV/DL import with staging and preview; admin bootstrap token;
deprovisioning; the directory screens in the console.

**Out:** roles and the visibility function (P2 — model the tree, do not yet gate reads on it),
gateways, activity.

## Database (revisions 0024–0026, 0028)

```
0024  org_units, org_unit_closure, org_unit_managers, member_org_units
      backfill: teams → org_units(kind='team'); team_members → member_org_units;
                one root company unit; closure incl. depth-0 self rows
0025  members: employee_ref, manager_member_id, primary_org_unit_id, status widened,
      first_seen_at/last_seen_at
0026  directory_groups, group_org_unit_rules, member_invitations rework (unique open invite)
0028  workload_credentials → service_identities (rename, member_id → acts_for_member_id),
      keep generations and token hashes untouched
```

Backfill verification queries are part of the deliverable, not an afterthought: every member has
exactly one primary unit; closure has a self row per unit; no `member_org_units` row without a
matching unit; every live key still authenticates after 0028.

## Algorithms to implement properly

**Closure maintenance.** Insert: copy the parent's ancestor rows plus a self row. Move a subtree:
delete closure rows from outside-ancestors to inside-descendants, then insert the new ones, and
rewrite `path` for the whole subtree — in one transaction, with an audit row. Prove with a test
that moves a 3-level, 500-unit subtree and checks closure cardinality exactly.

**Path maintenance.** `path` is materialised (`/northwind/eng/ide-users`), unique per account,
with a `text_pattern_ops` index for prefix scans. Slug collisions within a parent get a numeric
suffix, deterministically.

**Group → unit mapping.** Rules are evaluated by `priority`, then by specificity. Evaluation is
idempotent and additive: a sync never deletes a manually created unit, and a rule that no longer
matches marks the derived membership closed (`valid_to`), never hard-deletes it.

**Sync reconciliation.** Directory pull is a three-way merge between the directory, the mirror
(`directory_groups`) and our state. Deterministic order of operations: upsert groups → upsert
members → close absent memberships → suspend absent members (only when the directory is
authoritative) → apply rules → write a sync report. Every run produces a report row with
counts, and a dry-run mode that produces the report without writing.

## Backend surface

```
GET   /v1/directory/org-units?scope=&kind=&depth=      tree or flat, cursor paginated
POST  /v1/directory/org-units                          create; parent required except the root
PATCH /v1/directory/org-units/{id}                     rename, reparent (audited)
GET   /v1/directory/org-units/{id}/members
GET   /v1/directory/members?q=&unit=&status=           search by name, email, employee_ref
PATCH /v1/directory/members/{id}                       unit, manager, job title, status
POST  /v1/directory/invitations                        single or batch
POST  /v1/directory/import/preview                     CSV / DL export → staged, diffed
POST  /v1/directory/import/commit                      idempotent, keyed by import id
GET   /v1/directory/groups                             mirrored groups + counts + last sync
POST  /v1/directory/groups/{id}/rules                  map group → unit (+ optional role)
POST  /v1/directory/sync                               run now; dry_run supported
GET   /v1/directory/sync/runs                          history with counts and errors
POST  /v1/scim/v2/Users  · PATCH · DELETE              SCIM 2.0 inbound
POST  /v1/scim/v2/Groups · PATCH
POST  /v1/bootstrap/claim                              single-use admin bootstrap token
```

SCIM must be a real implementation, not an approximation: `externalId` honoured, PATCH
operations applied per RFC 7644, `active=false` deactivates, list filtering supported, errors in
the SCIM error shape. Half-implemented SCIM causes silent drift, which is worse than not
offering it.

## Frontend

- **Directory** screen: tree on the left (virtualised, expand/collapse, search), member table on
  the right with server-side pagination. 20k members must feel the same as 200.
- **Org unit detail**: members, managers, child units, grants (read-only this phase), source
  badge (manual / SCIM / sync / bulk), external ref.
- **Invite**: single and batch, with a preview of what will be created and who will be able to
  sign in.
- **Import**: upload → preview diff (create / update / close / suspend) → commit, with the
  report kept and linkable.
- **Sync**: provider status, last run, counts, errors, "run now" and "dry run".
- **Profile**: my units, my manager, my identities, my sessions, my keys, and a plain-language
  statement of who can see my activity — that last one buys a lot of trust.

## Invariants to add

| Name | Assertion |
|---|---|
| `inv_one_primary_unit` | A member has at most one open primary membership |
| `inv_closure_consistent` | Closure cardinality equals the tree's transitive closure after any move |
| `inv_sync_idempotent` | Running a sync twice with unchanged input writes no second-run changes |
| `inv_suspension_cascades` | Suspending a member revokes sessions and disables every service identity that acts for them |
| `inv_bootstrap_token_single_use` | A consumed bootstrap token cannot grant a second owner |
| `inv_import_is_idempotent` | Committing the same import id twice is a no-op |

## Test plan

1. Unit: closure insert/move/delete with exact row-count assertions; path rewrite; slug collision.
2. Unit: rule evaluation order and additivity; a rule that stops matching closes membership.
3. Integration: import 30 groups × 200 members from a fixture DL export; assert counts, then
   re-import and assert zero changes; time it and record the number.
4. Integration: SCIM create → update → deactivate; assert session revocation and key disabling.
5. Integration: LDAP pull against a containerised OpenLDAP fixture; assert the same end state as
   the SCIM path (one reconciler, two sources).
6. Integration: reparent a subtree and assert membership, closure, paths and the audit row.
7. Playwright: directory tree with 2 000 units and 20 000 members renders and searches under 2 s.

## Acceptance criteria (the gate)

- [ ] 30 DLs × 200 members imported; re-import is a no-op; the run report is visible in the UI.
- [ ] A DL from the directory appears as an org unit with its external ref and correct count.
- [ ] Reparenting rewrites closure and paths, and is audited.
- [ ] Suspending a member revokes their sessions and disables their keys within one cycle.
- [ ] The first administrator exists only via a consumed, audited bootstrap token.
- [ ] Every live platform key still authenticates after revision 0028.

## Deliverables

Revisions 0024–0026, 0028 with backfill verification; `directory` domain (router, service,
repository, schemas); SCIM router; sync workers (Graph, LDAP); import staging; bootstrap claim;
directory, import, sync and profile screens; six invariant tests; updated `PROJECT_STATE.md`.

## Do not

- Do not gate any read on visibility yet — P2 owns that, and doing both at once makes an
  authorization bug impossible to localise.
- Do not keep `teams` alive in parallel: migrate it and leave the old table in place, unused,
  for the contract migration in P2's wake.
- Do not invent a second hierarchy (tags, labels, cost-centre trees). One tree.
