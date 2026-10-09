# Phase 9 — Deployment packaging, offline enforcement, integrations

> **HISTORICAL — DO NOT EXECUTE.** Superseded by
> [`p-packaging.md`](p-packaging.md), which uses the reduced deployment model and the
> ledger/V1 bundle contracts.

> Paste this whole file as the only prompt of a fresh session.

## Objective

Make the product installable in a customer's VPC or data centre by their platform team, with the
vendor unable to read a payload, enforcement that survives losing the control plane, telemetry that
lands in the customer's SIEM, and the evidence an auditor asks for.

## Prerequisite

Phases 0–8 gates. This phase packages what exists; it should add no new enforcement semantics.

## Read first

- `design/01-deployment-and-tenancy.md` — modes, the bundle contract, the "what the vendor can see" table
- `design/08-activity-and-scale.md` — retention and failure modes
- `design/11-phase-plan.md` — the gate

## Scope

**In:** Helm chart for the data plane; the signed-bundle protocol end to end; offline and air-gapped
operation; OTLP and SIEM export; IdP integration hardening (SCIM certification-level behaviour,
SAML, LDAP); approval channels (Slack, Teams, email, generic webhook); evidence packs; the trust
page; upgrade and rollback; the install verifier.

**Out:** new product features. If something is missing, it belongs in a phase of its own rather
than smuggled into packaging.

## Deliverable 1 — the data-plane chart

One chart, one values file, documented. Components: model gateway, MCP gateway (with the stdio
sandbox), collector, queue, ClickHouse, token vault, policy cache, payload store binding.

Requirements:

- No vendor egress required except the control-plane link, and that link is one host and one port,
  named in the values file so a firewall team can approve it in one line.
- Bring-your-own for Postgres, object storage, KMS, queue and ClickHouse; each replaceable by an
  existing managed service the customer already runs.
- Resource requests and limits with a sizing table for 1k / 10k / 100k members.
- Zero-downtime upgrade; the gateway drains inflight streams before terminating.
- `helm test` runs the install verifier below.
- Secrets from the customer's secret manager, never from values, with a preflight that fails the
  install rather than starting insecurely.

## Deliverable 2 — the bundle protocol, finished

| Property | Requirement |
|---|---|
| Signing | Asymmetric, key rotation supported, public key pinned at install |
| Monotonic | The data plane refuses a version lower than it is running |
| Expiry | Every bundle carries one; behaviour on expiry is fail-closed for regulated classes, allow-and-record otherwise, with alarms on both sides |
| Size | Compressed, delta where possible; a 20k-member account's bundle has a stated size budget |
| Verification | `POST /v1/bundle/verify` on the data plane reports the running version, digest, age and expiry, and the console shows it |
| Air-gap | Export a bundle as a signed file, import by hand, with the same verification path |

## Deliverable 3 — offline and air-gapped

- The data plane starts, enforces and buffers with **no** control-plane reachability.
- A documented, tested procedure for importing a bundle and exporting telemetry on removable media,
  including the integrity check on both ends.
- Licensing offline: signed licence with an expiry, and degradation that is documented rather than
  discovered.
- Local admin accounts with TOTP for the air-gapped mode, with password policy and lockout, since
  there is no IdP to lean on.

## Deliverable 4 — integrations

| Integration | Requirement |
|---|---|
| OTLP export | Traces and metrics to the customer's collector; GenAI attribute mapping, with the pinned semantic-convention revision recorded (they are still in development) |
| SIEM | Audit and decision events to Splunk HEC, Sentinel and a generic HTTP sink; batched, retried, at-least-once, with a dead-letter path |
| SCIM | Behaviour at certification level: filters, PATCH per RFC 7644, `active=false`, SCIM error shapes |
| SAML | SP-initiated and IdP-initiated, signed assertions, encrypted assertions optional, clock skew |
| LDAP | Bind, group pull, referral handling, TLS with a custom CA |
| Approvals | Slack, Teams, email and a generic webhook, with signature verification on callbacks and single-use action tokens |
| MDM bundles | Cursor Admin API payloads, Claude Code managed settings, Codex and Gemini config files, produced per account and environment |

## Deliverable 5 — evidence packs

A signed archive answering an auditor's real question: "show me that this policy was in force and
what it did."

Contents: the policy version and its bindings; the grants in force; the decisions produced in the
window (metadata only); the approvals with their approvers; the attestation evidence for every
endpoint used; the audit chain segment with its verification; a manifest with digests; a plain
covering note stating what the pack does and does not prove.

Generated for a window and a scope, audited on generation, and verifiable by a script we ship so
the customer does not have to trust our word about the chain.

## Deliverable 6 — the install verifier

`aapctl verify` (also `helm test`) checks and prints a pass/fail line each for:

1. every dependency reachable, with versions;
2. secrets resolvable from the customer's manager;
3. bundle received, signature valid, version and expiry printed;
4. a governed model request completes, with added latency measured;
5. a governed MCP `tools/list` and `tools/call` complete;
6. an inspection blocks a synthetic secret;
7. an event reaches storage and is queryable;
8. audit chain verifies from genesis;
9. residency attestation present for every enabled endpoint;
10. no component can reach the public internet except the declared hosts.

The output is the install report, and it is what the customer's platform team sends their security
team. Make it something a person can paste into a ticket.

## Invariants to add

| Name | Assertion |
|---|---|
| `inv_no_payload_egress` | No data-plane component sends a payload byte to a vendor host (assert with an egress-blocking test fixture) |
| `inv_offline_enforces` | With the control plane unreachable, enforcement continues and denials still fire |
| `inv_bundle_monotonic` | A lower bundle version is refused |
| `inv_expired_bundle_fails_closed` | Past expiry, regulated classes are denied |
| `inv_unsigned_bundle_refused` | An unsigned or badly signed bundle is refused and alarms |
| `inv_evidence_pack_verifies` | A generated pack verifies with the shipped verifier, and a tampered one fails |
| `inv_install_verifier_covers_all` | The verifier fails when any single dependency is misconfigured |

## Test plan

1. Fresh install on a clean Kubernetes cluster from the chart only, following the written runbook,
   timed. Anything requiring a step not in the runbook is a defect in this phase.
2. Air-gap simulation: no egress at all; import a bundle from a file; export telemetry to a file;
   verify both.
3. Upgrade test: N → N+1 with traffic running; assert zero failed requests and no dropped streams.
4. Rollback test: N+1 → N with traffic running; same assertions.
5. Chaos: each dependency down in turn; assert the documented failure mode from
   `design/08-activity-and-scale.md`, and that the banner and alerts fire.
6. SIEM test: audit events land in Splunk HEC and Sentinel fixtures with correct field mapping and
   a working dead-letter path.
7. Evidence pack: generate, verify, tamper, verify again and assert failure.

## Acceptance criteria (the gate)

- [ ] A platform engineer installs the data plane in a customer-like VPC from the runbook alone.
- [ ] The vendor cannot read a payload — demonstrated with an egress-blocked test, not asserted.
- [ ] Enforcement survives the control plane being unreachable, and fails closed for regulated classes on expiry.
- [ ] Audit and decision events reach a SIEM fixture with correct mapping and retry.
- [ ] An evidence pack generates and verifies, and a tampered pack fails verification.
- [ ] `aapctl verify` covers all ten checks and produces a report fit to attach to a ticket.
- [ ] Upgrade and rollback run with traffic and no failed requests.

## Deliverables

Helm chart plus values and sizing table; bundle signing, verification and air-gap import/export;
offline licensing and local admin accounts; OTLP, SIEM, SCIM, SAML, LDAP and approval-channel
integrations; MDM bundle generation; evidence packs with the verifier; `aapctl verify`; the trust
page; install, upgrade and rollback runbooks under `docs/ops/`; seven invariant tests; updated
`PROJECT_STATE.md`.

## Do not

- Do not require vendor egress for any enforcement path.
- Do not add a feature here. Packaging phases that grow features never finish.
- Do not ship a runbook that has not been followed end to end by somebody who did not write it.
- Do not claim a compliance certification. Ship the evidence that supports an assessment, and say
  exactly that.
