# V1a — Cedar policy and simulation

> Paste this whole file as the only prompt of a fresh session.
> Prerequisite: MVP gate (M5) demonstrated. Do not start this to "get ahead" of ingest.

## Objective

Administrators author **structured rules** that compile to Cedar. Cedar is the audit
artefact and the simulation target, never the authoring surface. Simulate against the last
30 days of ledger data **before** activation.

## Read first

- `design/14-ai-identity-and-authorization.md` §6–§8
- `design/04-authorization-and-dashboards.md` amendment (D-13 / D-068)
- `design/15-capability-governance.md` §6–§7
- Existing `app/domains/policy/`
- Existing `policies`, `policy_versions` and `policy_decisions` migrations/models

## Scope

**In:** policy, policy_version, binding, simulate, activate, rollback. Exceptions and
break-glass with **mandatory expiry**. UI: form that compiles to Cedar, diff, simulate
results (would-deny / would-allow on historical actions). Decisions in MVP remain
**annotate-only** unless V1b is also done — default `outcome=annotate` so a bad policy
cannot outage developers.

Extend the existing policy domain and tables; do not create a parallel engine. Add only
missing bindings, simulation runs/results, activation metadata, exceptions and break-glass
records in the next revision after the real head. Every version is immutable. Activation
is a separate audited mutation. A rollback publishes a new version with prior content.

Before adding a Cedar runtime dependency, stop and obtain the dependency approval required
by `AGENTS.md`, documenting the candidate library, license, maintenance state and whether
evaluation can run in BYOC/air-gap. Do not implement a home-grown Cedar parser as a
workaround.

**Out:** hook deny (V1b), broker (V1c), OPA/Rego, writing Cedar by hand in the UI.

## Gate

- [ ] Simulate on a known `curl` to a production host returns would-deny for a draft rule.
- [ ] Activate without simulate is 422.
- [ ] Permanent exception cannot be inserted.
- [ ] Policy text stored is Cedar; UI never requires the admin to write it.
- [ ] Existing policy APIs remain compatible or have a versioned migration path.
- [ ] Cross-org simulation and activation are rejected in real-Postgres tests.

## Do not

- Do not let a numeric risk score convert deny → allow.
- Do not evaluate policy on raw argument bodies (there are none). Facets only.
