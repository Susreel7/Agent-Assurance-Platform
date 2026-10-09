# V1c — MCP as a capability binding + credential broker

> Paste this whole file as the only prompt of a fresh session.
> Prerequisite: V1a. Can overlap V1b. Existing MCP registry (`0017`, `/admin/mcp`) is the
> starting point — generalise, do not rebuild.

## Objective

1. MCP `tools/call` is one binding of `mcp.tool`. Unprivileged members cannot see or call
   a server they are not granted. Snapshots stay pinned (CVE-2025-54136). Unparseable
   arguments deny.
2. Token vault becomes a **broker**: per-task leases, short-lived, audience-bound
   (RFC 8707), sender-constrained if the downstream supports it. This is the Grade A
   answer to AP-1 for the three destructive surfaces we can broker (cloud API, VCS write,
   database) — not for a token already sitting on disk.

## Read first

- `design/06-mcp-gateway.md` (amended)
- `design/15-capability-governance.md` §4–§7
- `design/14-ai-identity-and-authorization.md` §5
- Existing `mcp_registry` domain, MCP onboard UIs

## Scope

**In:** wire `capability_grants` to existing `mcp_grants` or dual-read; keep digest
quarantine; description stored as digest + escaped text, never markdown-rendered to an
approver; add `credential_bindings` and `credential_leases` in the next hand-written
revision after the real head; issue lease on grant of `cloud.api` / `vcs.write` /
`db.query` when a binding exists. Platform Keys (D-062) remain the machine identity that
mints leases.

Reuse existing `provider_connections`, secret versions, connection grants,
`workload_credentials`, `mcp_servers`, snapshots, capabilities and grants. Generalize by
expand → backfill → dual-read:

1. Add capability source/definition/grant projections or tables without renaming/dropping
   live MCP tables.
2. Backfill every MCP capability and verify list/call results are identical.
3. Move one read path at a time.
4. Contract/remove legacy names only in a later prompt after a full proven phase.

The broker is an adapter over customer Vault/cloud IAM/OAuth token exchange, not a secret
store replacement. A binding points to a provider abstraction and scope template. A lease
records audience, scope, task, expiry and proof method; it never stores readable downstream
credential material. If a downstream cannot mint short-lived credentials, label the
binding unsupported or proxy the call—do not copy a long-lived token into the agent.

**Out:** becoming HashiCorp Vault. Becoming an MCP marketplace. Brokering every SaaS.

## Gate

- [ ] Unprivileged member: registry list omits the server; call is 403.
- [ ] Rug-pulled tool (snapshot digest change) does not take effect until re-approved.
- [ ] Lease TTL ≤ 15 minutes default; join `lease_id` on the action row.
- [ ] API cannot read back the upstream secret; only issue a new lease.
- [ ] Existing MCP list and call outcomes are identical before and after dual-read.
- [ ] A lease for task A cannot be used by task B or against another audience.
- [ ] Broker outage has an explicit fail-closed behavior for new destructive leases.

## Do not

- Do not inject long-lived upstream tokens into the agent environment.
- Do not claim the broker stops a token the agent already found on disk — detection of
  that remains M4. The broker stops **our** credentials being long-lived.
- Do not rename or drop the `mcp_*` or connection tables in the first broker revision.
