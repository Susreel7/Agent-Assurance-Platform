# P — Packaging (customer-VPC)

> Paste this whole file as the only prompt of a fresh session.
> Prerequisite: MVP gate. Prefer after V1a so policy bundles exist, but a read-only data
> plane can ship earlier if a design partner needs it.

## Objective

The same images run SaaS, customer-VPC, and self-hosted. No vendor access to payloads
(there should still be none). Signed policy bundles, heartbeat, SIEM export of
**content-free** action events.

## Read first

- `design/01-deployment-and-tenancy.md` (amended — **three** modes, not five)
- `AGENTS.md` deployment modes
- Threat model AP-8 (bundle rollback / widening)
- Existing `deploy/`, Compose, Helm, gateway and Observe deployment assets

## Scope

Extend the deployment mechanism already present; do not introduce Helm merely because the
prompt says customer-VPC. Signed bundles, refuse unsigned / rollback / silent permission
widen, OTLP/SIEM export of `aap.action.v1`, health/readiness, backup/restore and runbooks.
Air-gap is a self-hosted variant with documented bundle transfer, not a fourth product.

Deployment matrix:

- SaaS control plane + customer data plane (default)
- fully self-hosted / customer-VPC
- local development
- air-gap is an operational profile of self-hosted, not another code mode

Reconcile this wording with `AGENTS.md` before changing mode enums; record a decision rather
than silently creating both `byoc` and `customer_vpc`.

## Gate

- [ ] Customer-VPC install brings up API + web + collector ingest.
- [ ] Bundle with lower version is refused and audited.
- [ ] Export contains no prompt/argument bodies (test).
- [ ] Fresh install, upgrade from previous version, backup and restore are demonstrated.
- [ ] Air-gap install performs no DNS or egress attempt in an integration test.

## Do not

- Do not add Kafka or ClickHouse to make packaging look "enterprise".
- Do not phone-home on the critical path.
