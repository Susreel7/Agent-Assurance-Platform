# 02 · Identity, login and onboarding

Sketches: `diagrams/02-identity-and-onboarding.excalidraw`, `diagrams/03-hierarchy-and-visibility.excalidraw`

> **Amended 2026-09-22 — D-12.** The three principal kinds here (human, service identity,
> agent) cannot answer *who is responsible for an AI action*. The model is extended to
> `Human → Agent → Agent Version → Agent Instance → Session → Task → Action`, with
> delegation expressed as RFC 8693 `sub`/`act` semantics, authority that attenuates and never
> widens across a hop, and a delegation-depth cap. Two rules are non-negotiable: **every
> action has a human at the root** (with `root_human_basis` recording *why*, so evidence
> never implies someone was at a keyboard when they were not), and **a service identity may
> never be the root of an action chain**. See
> [`14-ai-identity-and-authorization.md`](14-ai-identity-and-authorization.md) §1–§4.
>
> The org-unit tree, closure table, DL import and scoped-visibility work in this document is
> unchanged and correct.

Every screen in the console depends on this being correct, which is why it is phase 1 and
why the current implementation's login problems are a structural fix, not a patch.

## The rule that removes today's whole bug class

> **The browser must never decide how authentication works.**

Today the web app reads `VITE_OIDC_ISSUER` / `VITE_OIDC_CLIENT_ID` at build time, decides
by itself whether Entra is "configured", persists a session *before* server-side onboarding
has succeeded, keeps it in `sessionStorage`, and then loads each screen through separate
queries that can each independently return 403. Any one of those failing paints "unable to
login with Entra ID" or "Something went wrong · Try again" with no reason attached. A reload
finds a saved-but-unbacked session, so the second failure looks different from the first.
That is exactly the behaviour reported.

Three endpoints replace it:

```http
GET  /v1/auth/config?email_domain=northwind.example
     → { account_hint, providers: [{ id, kind, label, authorize_url, client_id, scopes,
           pkce: true }], onboarding_mode, dev_bypass: false }

POST /v1/auth/session      { provider_id, code, code_verifier, redirect_uri }
     → verifies the code server side, resolves or provisions the member, applies the
       onboarding mode, issues *our* session cookie/token, and only then returns 200.
       Any failure returns a typed error and no session exists anywhere.

GET  /v1/session/bootstrap
     → { member, account, org_units, roles, permissions, visibility, navigation,
         capabilities, environments, freshness }
```

Consequences:

- The token exchange happens server side, so the client secret question, the redirect-URI
  mismatch class of error, and clock-skew handling all live in one place with real logging.
- The session is created **after** onboarding, so "a session exists but the member is not
  bound" becomes unrepresentable.
- The shell renders from exactly one response. There is no window where navigation exists
  but permissions do not.
- Deployment mode E (development) is a *provider kind* returned by `/v1/auth/config`, not a
  build flag and not a magic `dev.<email>` bearer token accepted by the API. It is refused
  unless `accounts.deployment_mode = 'development'`.

Session transport: `HttpOnly; Secure; SameSite=Lax` cookie holding an opaque reference, with
a server-side session record (revocable, listed in the profile page, revoked on
deprovision). Not `localStorage`, not `sessionStorage`, not a bearer token in JS. Silent
renew through a refresh endpoint; a 401 triggers one renew attempt and then a clean
redirect that preserves the deep link.

## Auth providers are data

```sql
CREATE TABLE auth_providers (
  id                uuid PRIMARY KEY,
  account_id        uuid NOT NULL REFERENCES accounts(id),
  kind              text NOT NULL,          -- oidc | saml | ldap | local | development
  label             text NOT NULL,          -- "Sign in with Northwind" — shown on the button
  issuer            text,                   -- OIDC issuer / SAML entity id / LDAP URI
  client_id         text,
  client_secret_ref uuid REFERENCES connections(id),   -- vaulted, nullable for PKCE
  jwks_uri          text,
  authorize_url     text,
  token_url         text,
  claim_map         jsonb NOT NULL,         -- see below
  group_claim       text,                   -- e.g. "groups" | "roles" | memberOf
  email_domains     text[] NOT NULL,        -- account discovery, and the JIT allowlist
  onboarding_mode   text NOT NULL,          -- scim | directory_pull | jit | invite | bulk
  require_mfa_claim boolean NOT NULL DEFAULT false,
  precedence        int NOT NULL DEFAULT 100,
  enabled           boolean NOT NULL DEFAULT true,
  UNIQUE (account_id, issuer)
);
```

`claim_map` is how one code path serves Entra, Okta, Keycloak, PingFederate and ADFS without
per-vendor branches:

```json
{
  "subject":   "oid",
  "email":     ["email", "preferred_username", "upn"],
  "name":      ["name", "displayName"],
  "employee_ref": ["employeeid", "onprem_sam_account_name"],
  "manager":   ["manager_upn"],
  "groups":    "groups",
  "mfa":       { "claim": "amr", "contains": ["mfa", "hwk", "otp"] }
}
```

Rules: arrays are tried in order and the first present, non-empty value wins; `subject` is
never derived from an email (emails get reused and renamed, `oid`/`sub` does not); an email
is only treated as verified if the provider says so or the provider is marked as
domain-authoritative.

### Auth by deployment mode

| Deployment | Primary auth | Group/DL source | Admin bootstrap |
|---|---|---|---|
| SaaS | Customer Entra/Okta OIDC, discovered by email domain | SCIM push, or Graph group read if egress allowed | Signed provisioning token from the onboarding flow, single use |
| Single tenant | Same | Same | Same, issued by the provisioning job |
| Self-hosted | Customer OIDC (Entra, Keycloak, PingFed) or SAML | SCIM, LDAP pull, or CSV | Installer-sealed bootstrap credential printed once by the Helm job |
| Air-gapped | LDAP/AD bind, or local accounts + TOTP | LDAP pull | Offline licence + sealed credential, physically delivered |
| Development | Local stub provider | Fixture | Explicit `bootstrap` CLI, refuses to run outside development mode |

There is exactly **one** way an account gets its first administrator, per deployment. It is
a single-use, auditable token — never "the first person who logs in", which is how the
current implementation ended up bootstrapping owners implicitly and inconsistently.

## Onboarding modes

| Mode | Direction | Authoritative for | When to choose it |
|---|---|---|---|
| `scim` | IdP → us (push) | Members, attributes, group membership, deactivation | The customer has SCIM. Best. Deactivation is immediate. |
| `directory_pull` | We → IdP/LDAP (scheduled) | Same, at sync cadence | On-prem AD, or Entra without SCIM. 15-minute cadence, delta where available. |
| `jit` | On first login | Member creation only | Fast pilots. Requires `email_domains` allowlist and a default org unit. Cannot deactivate — pair with either of the two above later. |
| `invite` | Admin action | Member creation | Default when nothing is connected. First matching login claims the invitation. |
| `bulk` | CSV / DL export | One-off | Pilot with 200 people and no directory access yet. Staged → previewed → committed as invitations. |

All five converge on the same resolver so there is one code path to test:

```
resolve(provider, claims):
    sub   = claims[claim_map.subject]
    email = normalise(first_present(claims, claim_map.email))

    identity = member_identities[issuer=provider.issuer, subject=sub]
    if identity: member = identity.member                          # returning user
    else:
        member = members[account, lower(email)] if email_verified else None
        if member:      link_identity(member, provider, sub)       # new IdP subject, known person
        elif mode == 'jit' and domain_allowed(email):
            member = provision(email, claims, default_org_unit)
        elif invitation := open_invitation(account, email):
            member = claim_invitation(invitation, provider, sub)
        else:
            raise NotProvisioned(reason='no_member_or_invitation')  # 401, actionable text

    apply_group_mappings(member, claims[claim_map.groups])          # idempotent
    record_login(member, identity, mfa=…, ip=…, agent=…)
    return bootstrap(member)
```

Everything in that function is idempotent. Logging in twice, or a SCIM replay, or a directory
sync overlapping a login, must converge on the same rows.

## Distribution lists and the hierarchy

The concrete shape to fit: **one account, 30+ distribution lists, 200+ people in the Cursor
DL, one admin monitoring that DL, a few admins above all DLs.**

One tree, one table. A DL is not a special entity:

```
org_units(kind)  = company | business_unit | department | team | distribution_list | cost_centre
org_units(source) = manual | scim | directory_pull | bulk
org_units(external_ref) = the DL/group object id in the directory  (unique per account)
```

- `directory_groups` holds the raw group/DL as the directory reports it (object id, display
  name, member count, last sync). It is a mirror, never edited by hand.
- `group_org_unit_rules` maps a raw group to an org unit, and optionally to a role grant:
  `group "CORP-ide-users" → org_unit "ide-users" (+ no role)`, and
  `group "NW-IDE-Admins" → org_unit "ide-users" + role dl_admin (subtree)`.
  This is how "one admin monitors 200 people" becomes automatic and survives staff changes:
  the customer manages their DL, we derive the access.
- A member can belong to many org units (`member_org_units`, one row marked primary). Cost
  is attributed to the **primary** unit so totals never double-count; visibility uses **all**
  memberships so nobody loses sight of a matrixed report.
- Managers: `org_unit_managers(org_unit_id, member_member_id, subtree bool)`. Multiple
  managers per unit, and a manager need not be a member of the unit.

Reparenting a subtree rewrites `path` and `org_unit_closure` for the moved descendants in one
transaction, and writes an audit row. Historical activity keeps the `org_path` it was
recorded with, so last quarter's report does not silently change when a reorg happens — with
an explicit "restate under current structure" toggle for people who want the other answer.

## Leaving, transferring, suspension

The part that most implementations forget, and the part auditors always ask about.

| Event | Effect, within one sync cycle |
|---|---|
| SCIM `active=false`, or absent from a directory pull | `members.status = 'suspended'`, all sessions revoked, every `service_identity` that `acts_for` them disabled, their grants marked inactive (not deleted) |
| Transfer to another org unit | New primary membership; old membership closed with `valid_to`; activity history keeps its original `org_path`; grants scoped to the old unit expire |
| Deletion request (GDPR) | Member row pseudonymised, identities dropped, activity rows keep the id but the display resolves to "removed member #1234". Audit rows are never deleted. |
| Manager change | `org_unit_managers` updated by the mapping rules; dashboards follow on the next bootstrap |

Agent and platform keys are never orphaned: a key whose `acts_for_member` is suspended stops
authenticating, which is the only behaviour a security team will accept. Ownership transfer
is an explicit, audited action.

## Failure taxonomy the UI must render

Each of these has a reason code, an HTTP status, a human sentence and a next action. This
table is the contract between the API and the console, and it is what stops "Something went
wrong · Try again".

| Reason code | Status | What the user sees | Next action |
|---|---|---|---|
| `session_expired` | 401 | nothing — silent renew | transparent |
| `not_provisioned` | 401 | "Your account is not set up for the AI Control Plane yet." | Request access (emails the account owner) |
| `provider_disabled` | 401 | "Sign-in with *Northwind* is turned off." | Contact owner, named |
| `mfa_required` | 401 | "Your organisation requires MFA for this console." | Re-authenticate with MFA |
| `module_forbidden` | 403 | "You need the *Security admin* role to open Incidents." | Request the role, with who can approve |
| `scope_outside_grant` | 403 | "That org unit is outside your visibility." | Shows which units they can see |
| `payload_withheld` | 200 + flags | Field renders locked with a reason | Request payload reveal (approval) |
| `approval_pending` | 409 | "Awaiting approval from *Priya*, requested 4m ago." | Open request, nudge |
| `policy_denied` | 403 | The policy id, the class detected, the alternative alias | Named alternative, one click |
| `bundle_stale` | 503 | "Enforcement is running on a cached policy from 12:04." | Retry; the banner is global, not per screen |

The console's error boundary never renders a bare message. If a response has no reason code,
that is a bug in the API, and the boundary says so with the request id.
