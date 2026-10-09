# 01 · Deployment and tenancy

Sketch: `diagrams/01-deployment-topology.excalidraw`

> **Amended 2026-09-22.**
>
> **D-15** — deployment modes reduce from five to **three**: SaaS control plane + customer
> data plane (default), fully self-hosted, local development. Air-gapped becomes a
> self-hosted variant with a documented bundle-transfer procedure, not a separate mode. A
> small team cannot support five topologies and ship a wedge.
>
> **D-11** — the outbound-only-egress promise below is **false for Cursor**. With base-URL
> routing it is Cursor's cloud that calls our data plane, so the endpoint must be reachable
> from the public internet. See [`05-model-gateway.md`](05-model-gateway.md) and
> [`13-threat-model.md`](13-threat-model.md) §2 (trust boundary TB-3).
>
> **AP-8** — the bundle rules below are strengthened: the data plane must refuse any bundle
> that is unsigned, has a **lower version than the running one** (rollback attack), or
> **widens** effective permissions past a customer-set ceiling without a second signature.
> Bundle-activation evidence is written on the customer side.
>
> The failure-mode table in [`13-threat-model.md`](13-threat-model.md) §8 supersedes and
> extends any fail-open/fail-closed statement in this document.

## The split

Two planes, one product.

**Control plane (vendor cloud, or the customer's management subscription).** Admin console,
policy authoring and signing, asset registry, identity and access configuration, rollups,
risk scores, billing. Holds *metadata about* AI activity. Holds no prompts, no completions,
no tool arguments, no provider credentials.

**Data plane (customer VPC, data centre, or air-gapped network).** Model gateway, MCP
gateway, inspection and DLP, token vault, payload store, policy cache, telemetry collector.
Holds everything sensitive. Talks outbound only.

The link carries exactly two things:

- **down:** a signed, versioned policy bundle (policies, grants, aliases, endpoints,
  capability snapshots, price book) with an expiry;
- **up:** signed telemetry envelopes — counts, digests, decisions, reason codes, token and
  cost numbers, never bodies.

### Why this way

A single-cloud SaaS that proxies prompts is unsellable to a security team that is buying us
*because* they are worried about where prompts go. A pure on-prem product cannot be
operated or upgraded at the pace this category moves. The split lets the customer keep the
payloads and lets us keep the product.

### Non-negotiable consequences

| Rule | Why |
|---|---|
| The control plane is never on the request path | Our outage must not stop the customer's engineers, and must not open access |
| The data plane enforces from cache | Bundle TTL, e.g. 15 minutes; on expiry, fail closed for regulated data classes, read-only allow for the rest, and raise an alarm both sides |
| Telemetry loss never blocks a decision | Bounded buffer, disk spool, then shed the `allow` path and keep every `deny` |
| Bundles are signed and monotonic | The data plane refuses an unsigned bundle or a version lower than the one it is running |
| Payload reads are local | The console asks the data plane for a payload through a scoped, audited, time-boxed request; it never stores one |

## Deployment modes

| Mode | Control plane | Data plane | Auth | Typical customer |
|---|---|---|---|---|
| **A · SaaS + customer data plane** (default) | Vendor cloud, multi-tenant | Customer VPC (Helm/ECS/AKS) | Customer IdP over OIDC | Enterprise with a cloud footprint |
| **B · Single tenant** | Dedicated vendor-managed instance in the customer's region | Customer VPC | Customer IdP | Regulated, cloud-friendly |
| **C · Fully self-hosted** | In the customer's management cluster | Same cluster or per-region | Customer IdP or LDAP/AD | Bank, telco, defence |
| **D · Air-gapped** | Self-hosted, no egress | Same network | LDAP/AD or local accounts + TOTP | Classified networks |
| **E · Local development** | Docker Compose | Same | Stub provider, explicit flag | Us |

One build, one schema, one migration path. Mode is an `accounts.deployment_mode` value plus
configuration; it is never a code fork. Anything that cannot be configured (for example
"can this deployment reach graph.microsoft.com for DL sync") is expressed as a **capability
flag** on the account, and the UI hides what the deployment cannot do rather than offering
it and failing.

```
accounts.deployment_mode      saas | single_tenant | self_hosted | air_gapped | development
accounts.capabilities         { egress_internet, scim_inbound, directory_pull,
                                slack_webhook, otlp_export, self_hosted_model }
```

## Tenancy

**One account = one tenant = one row in `accounts`.** Every tenant-scoped table carries
`account_id`, has it in its primary or unique keys, and is protected by Postgres row-level
security bound to a session variable set by the request middleware. Tenancy is not enforced
by remembering to add a `WHERE` clause in Python.

```sql
ALTER TABLE members ENABLE ROW LEVEL SECURITY;
CREATE POLICY members_tenant ON members
  USING (account_id = current_setting('aap.account_id')::uuid);
```

Inside an account, isolation is by **org unit** and **environment**, not by more tenants.
A company with three subsidiaries that must not see each other is still one account with an
org-unit boundary and no cross-unit grants — otherwise cross-subsidiary reporting becomes
impossible and every admin ends up with two logins.

**Environments** (`dev` · `staging` · `prod`) are a first-class dimension on grants,
endpoints, MCP servers and policies. A key that works in dev must not work in prod, and the
console must never show a single merged view that hides which environment an action was in.

## What the vendor can see, stated plainly

This table goes in the security questionnaire and in the product's own trust page.

| Data | Control plane | Data plane |
|---|---|---|
| Prompt and completion bodies | No | Yes, encrypted at rest with the customer's key, TTL-bounded |
| Tool call arguments and results | No | Yes, same |
| Digests, counts, token and cost numbers | Yes | Yes |
| Member names and email addresses | Yes (needed to render a console) | Yes |
| Provider and MCP credentials | No | Yes, KMS-wrapped, never returned by an API |
| Policy documents, grants, aliases, capability snapshots | Yes | Yes (cached) |
| Detokenisation map | No | Yes |

Pseudonymous mode, for customers who will not send names to a vendor: the data plane
substitutes stable pseudonyms for member identifiers in telemetry and keeps the map locally;
the console renders pseudonyms until an operator, inside the customer network, resolves
them. This is a configuration flag, not a separate product.

## Runtime shape of the data plane

| Component | Language | Scaling | Notes |
|---|---|---|---|
| Model gateway | Go | Stateless, HPA on inflight requests | Owns streaming; must not buffer whole responses |
| MCP gateway | Go or Python (decide at P5; Go preferred for stdio pooling) | Stateless plus a per-server session pool | Holds upstream credentials |
| Inspector (DLP) | Rust or Go library, in-process | Scales with the gateway | In-process, not a network hop — this is a p95 budget decision |
| Token vault | Postgres or Redis with KMS envelope | Small | TTL-bounded, per-account key ring |
| Collector | Go | Stateless | Batches to the queue, disk spool |
| Policy cache | In-process, 5 s TTL + invalidation channel | — | Zero database calls on the request path |

Deliberately excluded from the request path: the control-plane API, the Postgres that holds
configuration, ClickHouse, and anything that does DNS at request time.

## Sizing target to design against

Stated so every later decision can be checked against it.

| Dimension | Design point | Burst |
|---|---|---|
| Governed model requests | 100k per 30 min ≈ 56/s | 560/s |
| Tool calls | ~4 per request ≈ 220/s | 2 200/s |
| Events per second | ~280 | ~3 000 |
| Events per day | ~25M | — |
| Added latency, policy + routing | p95 < 12 ms | p99 < 25 ms |
| Added latency, inspection on 32 KB | p95 < 8 ms | — |
| Dashboard read | p95 < 300 ms from rollups | — |
| Members per account | 20k | 100k |
| Org units per account | 2k | 10k |
