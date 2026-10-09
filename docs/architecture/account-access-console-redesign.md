# People, agents, registries, access, gateway and console redesign

**Status:** Consolidated master draft for owner approval; no implementation authorized  
**Created:** 2026-09-17  
**Tracks:** Q-013, Q-014, Q-015, Q-017, Q-023 and Q-024  
**Depends on:** Agent Execution Observability Phase 13 certification

## Product objective

Make the platform useful to both people and agents:

1. every human signs in with a verified identity;
2. every agent and service uses a separately revocable workload identity;
3. permissions can be assigned at account, project, environment and agent scope;
4. provider credentials are protected connections, not API keys copied into agents;
5. the gateway enforces model, MCP and A2A access for the verified actor;
6. Observe connects the initiating person to every effective human, agent or service actor;
7. administrators can explain who may do what, who actually did it and who approved it;
8. the console presents this system with a quiet, coherent and accessible experience.

The company is the buyer. Agents, developers, operators, approvers and auditors are
different users of the same control and assurance system.

## Requirements traced from the design conversation

This document is the single implementation plan for the complete September 17 design,
not only the account/profile redesign.

| Conversation requirement | Planned here |
|---|---|
| Gateway is infrastructure, not code embedded into every agent | Gateway adoption and deployment topology |
| Existing Claude, Cursor, Azure, OpenAI and private-model agreements remain | Provider connections, two-key model and billing boundary |
| The company, human users and agents all receive value | Personas, unified activity, access and assurance |
| Cursor auto-review is not an enterprise control plane | Traffic coverage and runtime approval sections |
| Human profiles, admins, agent access and platform keys | Identity, roles, grants and Platform Keys |
| No visible “Organization” workflow | Account UI with an internal tenant boundary |
| MCP registry with user, team and agent-version access | Governed MCP registry and enforcement plane |
| Models, MCP, A2A, tools, data and memory need governed identities | Governed-resource architecture |
| Semantic cache and A2A state were proposed | Explicit staged scope and non-goals |
| Major backend and polished UI redesign | Domain/API plan, information architecture and delivery spine |

## Scope boundaries

Everything required for the intended platform is tracked, but not everything ships in
the first release.

### First licensed release

- verified login, members, teams, roles and scoped grants;
- non-superuser database role and functioning RLS;
- provider connections and Platform Keys;
- governed model catalogue and existing LLM gateway enforcement;
- governed MCP server/tool registry with manual registration, discovery snapshots and
  per-user/team/agent access;
- human and agent activity joined through trusted identities;
- company approval, audit and explainable denials;
- redesigned console shell and the core People, Agent, Connection and MCP screens.

### Subsequent enterprise releases

- complete MCP proxy behavior beyond tools into resources, prompts and bidirectional
  protocol features;
- A2A registry, mediation and task continuity;
- native HTTP, gRPC, SQL, data and memory connection enforcement;
- semantic cache after measured demand and a safety pilot;
- curated marketplace, SIEM integrations, chargeback and advanced incident response.

Semantic cache is not removed from the roadmap. It is deliberately after identity,
registry and enforcement because an embedding lookup without policy-aware tenancy,
versioning and invalidation is a data-leak feature, not a moat.

## Architecture decision requiring approval

### Remove “Organization” from the product language, not the security model

Literal removal of `organizations` or `org_id` is rejected by this draft. That identifier
is the current root for:

- PostgreSQL row-level security and every explicit tenant filter;
- SaaS billing, licences and module entitlements;
- BYOC and air-gap single-tenant ownership;
- identity-provider bindings;
- provider-secret namespaces;
- projects, agents, customers, engagements and evidence;
- gateway snapshots, workload credentials and Redis limit keys;
- Observe PostgreSQL, ClickHouse and object-store partitions.

Deleting it would be a full rewrite and would remove the isolation boundary the product
needs. It would also silently reverse D-006 and D-034.

The proposed product hierarchy is:

```text
Account                                  internal key remains org_id
├── People and teams
├── Projects
│   ├── Environments
│   ├── Agents and immutable versions
│   ├── Provider connections
│   └── Platform workload keys
├── Clients and engagements              assurance recipients, not login tenants
└── Policies, evidence and entitlements
```

Ordinary users never choose or type an account ID. SaaS resolves it from the verified
OIDC identity binding. BYOC and air-gap select their one account automatically.

`Account` is the recommended UI term. `Workspace` is not recommended because projects
already provide the collaborative scope and the two concepts would be confused.

## Governed-resource architecture

The product needs canonical identities for everything a person or agent may use. A
connection supplies authentication; a registry describes and versions the resource; an
access grant authorizes use; Observe records what actually happened.

| Resource | Source of truth | Versioned unit | Enforcement point |
|---|---|---|---|
| People and teams | members/access domains | identity and grant revision | Control-plane API and gateway delegation |
| Agents | existing registry | immutable agent version | API, gateway and Observe |
| Models/providers | existing model routing catalogue | catalogue entry and deployment | Go LLM gateway |
| MCP servers | new MCP registry | immutable discovery snapshot | Go MCP gateway |
| MCP tools/resources/prompts | MCP snapshot | schema/signature digest | MCP discovery and invocation |
| A2A agents | new A2A registry | Agent Card digest | A2A gateway |
| Native HTTP/gRPC/SQL tools | future tool registry | endpoint/schema digest | egress gateway or approved runtime |
| Data and memory sources | future connection registry | endpoint/classification policy | retrieval instrumentation and egress policy |
| Prompts, skills and rules | existing Prompt/composition services | immutable revision/digest | agent release and runtime policy |
| Provider secrets | connections domain | secret version reference | gateway secret lease |
| Platform Keys | workload identity | credential generation | gateway and ingest APIs |

### Registry, observed inventory and marketplace are different

These surfaces must never be merged:

1. **Registry** — curated, approved resources the account permits.
2. **Observed inventory** — telemetry describing what users and agents actually called.
3. **Marketplace** — optional external discovery of resources that may be imported into
   the registry after review.

Observed activity never silently creates an approved registry entry. An unknown server or
tool creates an `observed_only` finding and an administrator may start a reviewed
“promote to registry” flow.

### Effective access equation

An invocation is allowed only when all applicable controls permit it:

```text
account policy
∩ project/environment policy
∩ member/team grant
∩ initiating-user delegation
∩ workload credential scope
∩ immutable agent-version binding
∩ approved resource snapshot
∩ engagement/data/residency rules
∩ rate, budget and approval conditions
```

No single “admin”, Cursor approval, MCP annotation or agent prompt can bypass a hard deny.

## Identity model

### Human identity

- Authentication remains generic OIDC: Entra, Okta, Keycloak and Auth0 are configuration.
- The browser uses Authorization Code with PKCE.
- A human is identified internally by `(issuer, subject)`, never by mutable email.
- Email and display name are profile attributes refreshed from trusted claims.
- The API derives audit actor identity from `Principal.actor_ref`; request bodies may not
  choose `published_by`, `approved_by`, `triaged_by` or similar actors.
- Authentication and account resolution happen before any tenant session is opened.

### Workload identity

- Agents, collectors, CI and services use existing `aap_wk_*` workload credentials.
- A key is bound to account, project, environment, modules, scopes and optionally an agent.
- The plaintext is displayed once. Only a digest and generation metadata are stored.
- Human tokens cannot impersonate workloads and workload keys cannot approve human
  governance actions.
- OAuth2 client credentials may be added later for enterprises that prohibit long-lived
  keys, but must resolve to the same verified workload model.

### Runtime attribution

Every operation preserves:

- `initiating_user_id`: the human on whose behalf work began, when known;
- `effective_actor_id` and `effective_actor_type`: human, agent, service or scheduler;
- account, project, environment, agent and immutable agent version;
- telemetry coverage: complete, partial or unknown.

An initiating user supplied by an arbitrary client is not trusted. It must come from a
trusted application session, a gateway-issued delegation token or an explicitly bound
telemetry identity.

## User, team and access data model

Names are proposed; migration identifiers are deliberately not assigned before approval.

### `members`

- `id`
- `org_id`
- `status`: invited, active, suspended, disabled
- `display_name`
- `email`
- `created_at`, `last_seen_at`, `disabled_at`

Unique membership identity is not email. Multiple identities may belong to one member.

### `member_identities`

- `id`, `org_id`, `member_id`
- `issuer`, `subject`
- `identity_type`: oidc, local_airgap
- `email_last_seen`, `claims_digest`, `last_authenticated_at`

Unique on `(org_id, issuer, subject)`.

### `member_profiles`

- `member_id`, `org_id`
- default project
- timezone and display preferences
- notification preferences

Profiles contain presentation preferences, not authorization or provider secrets.

### `teams` and `team_members`

Teams are the normal assignment unit. Users should not need hundreds of individual agent
grants. A person may belong to multiple teams.

### `roles` and `role_permissions`

Built-in roles are immutable bundles. Custom roles are a later enterprise capability.
Authorization checks permissions, not role names.

### `access_grants`

- principal: member or team;
- role;
- scope: account, project, environment or agent;
- optional expiry;
- grantor and reason;
- created/revoked timestamps.

The effective permission is the union of valid grants within the requested resource
scope, followed by workflow separation and content-policy checks.

### `idp_group_role_mappings`

IdP groups may create or synchronize platform role assignments. Platform assignments
remain authoritative so agent-scoped grants, expiry and approver separation work
consistently across identity providers.

### `security_audit_events`

Append-only, tenant-scoped events for login, authorization denials, grants, credential
changes, secret leases, break-glass access, workload-key lifecycle and router publication.
Events contain references and digests, never secret material or customer payloads.

## Roles and permissions

The UI exposes understandable roles. The API enforces fine-grained permissions.

| Built-in role | Intended capability | Explicit restriction |
|---|---|---|
| Account owner | Account lifecycle and emergency recovery | Not routine approver of own work |
| Account admin | Members, teams, projects and ordinary settings | Cannot reveal provider secrets |
| Security admin | Connections, keys, policy, revocation and security audit | Cannot approve own release |
| Developer | Build agents, versions, prompts and evaluations in granted scopes | No production approval by default |
| Operator | Run agents, inspect metadata, respond to incidents and manage runtime | No policy or accreditation approval |
| Approver | Release, materiality and accreditation decisions | Must differ from publisher/editor |
| Auditor | Evidence, security audit and content-free reports | Read-only; protected payload requires separate grant |
| Viewer | Non-sensitive read access | No protected content, secret metadata or mutation |

The SaaS operator identity is separate from every customer account. `platform_admin`
must not silently grant access to customer content.

Important permission families:

```text
account:members:read|manage
account:roles:read|manage
projects:read|manage
agents:read|edit|run|publish|approve
connections:read|manage|use
platform_keys:read|issue|rotate|revoke
mcp_servers:read|register|discover|approve|bind|quarantine
mcp_tools:discover|invoke|approve_invoke
mcp_resources:discover|read
mcp_prompts:discover|use
a2a_agents:read|register|invoke|delegate|approve
tool_registry:read|register|invoke
data_connections:read|manage|use
router:read|configure|publish
observe:read|content:read|retention:manage
findings:triage|resolve
evidence:read|verify|export
accreditation:submit|approve
```

Licence entitlements answer whether a module exists. Permissions answer whether this
principal may perform this action. Both must pass.

## Credential and connection model

The console must not present one undifferentiated “API keys” page.

### 1. Provider connections

Examples: Anthropic API key, OpenAI project key, Azure OpenAI, Bedrock role, Gemini,
Cursor API integration, private vLLM endpoint, MCP OAuth client.

- Account- or project-owned.
- Created by an authorized user.
- Secret entered once and never returned.
- Metadata includes provider, endpoint, owner, project/environment scope, fingerprint,
  health, last use, rotation due date and allowed agents.
- A deployment stores `credential_ref`, never plaintext.
- Test-connection executes server-side with a bounded, non-content request.

### 2. Personal development connections

Optional and disabled by default for enterprise accounts.

- Owned by one member.
- Allowed only for development/playground unless policy explicitly widens it.
- Cannot be selected by production agents.
- Administrators see metadata and usage, not plaintext.
- The UI must state who pays the provider bill.

Personal keys do not belong in the general profile form. They live under
**Profile → Developer connections** only when the account enables BYOK.

### 3. Platform workload keys

These are issued by this platform and are not model-provider credentials.

- Bound to project, environment and optional agent.
- Carry module/scope/model limits.
- Displayed once with copy/download guidance.
- Rotatable with overlapping generations.
- Revocable immediately.
- Show last used, source, expiry and affected agents.

They live under **Agent → Runtime access** or **Control → Platform keys**, not in the
human profile.

### 4. Browser session

OIDC access and refresh tokens are session material, not API keys. They are managed by
the authentication client and never displayed as reusable credentials.

### Secret storage

The provider abstraction selects the implementation:

- SaaS: envelope encryption with a managed KMS;
- BYOC: customer KMS and secret manager;
- air-gap: customer-operated local secret provider;
- development only: existing gateway file/environment resolver.

The control-plane database stores secret metadata, version, owner, fingerprint and an
opaque provider reference. It does not store retrievable plaintext. The gateway obtains
short-lived secret leases over an authenticated internal channel and caches them only in
memory for a bounded TTL.

## Gateway adoption, deployment and traffic coverage

### Adoption model

The gateway is customer infrastructure. Agent code continues to use standard OpenAI,
MCP and A2A clients.

1. LLM applications change their `base_url` and use an AAP Platform Key.
2. Remote MCP clients change the server URL to the gateway MCP endpoint.
3. Local stdio MCP servers use a small local bridge that forwards standard MCP to the
   account gateway.
4. A2A clients use gateway-published Agent Card URLs.
5. `aap-trace` remains optional for graph nodes, state, checkpoints and work that cannot
   be seen at a network boundary.

The customer’s existing provider contracts and bills remain unchanged. The gateway uses
their provider connections; the platform charges for control, assurance and operation,
not for resold frontier-model tokens.

### Deployment topology

- **Recommended:** redundant gateway pool per region or trust zone.
- **Optional sidecar:** only for workload-level isolation or strict air-gap boundaries.
- **Developer mode:** local Docker plus stdio bridge.
- **Hosted:** SaaS gateway only where the customer accepts hosted traffic.

The default is not one sidecar per agent. That fragments health, cache, limits and
upgrades. Trust-zone pools provide consistent enforcement while remaining inside the
customer’s network in BYOC.

### Forced path and bypass detection

Policy is credible only when relevant network paths cannot bypass it:

- production workloads may reach provider, MCP and A2A endpoints only through the gateway;
- direct egress exceptions are explicit, expiring and audited;
- gateway and Observe compare declared endpoints with observed destinations;
- an execution with uninstrumented or direct traffic is marked partial or unknown.

### Traffic coverage

| Traffic class | Coverage |
|---|---|
| Customer application using gateway + trace SDK | Complete boundary and internal execution coverage |
| Customer application using only gateway | Complete boundary enforcement; partial internal execution |
| Cursor/Claude Code using custom model and MCP endpoints | Gateway-controlled paths are covered |
| Cursor/Claude using vendor-hosted default model | Unknown unless vendor telemetry or a separate network intercept exists |
| SaaS copilots that cannot change endpoints | Metadata-only or unknown; never represented as complete |

Cursor’s local auto-review remains a useful client safety check. It is not accepted as
company authorization because it does not carry account policy, agent-version approval,
cross-client consistency or independently verifiable evidence.

## Governed MCP registry and enforcement plane

MCP is a first-class control-plane resource, not a list of names attached to run
telemetry.

### MCP server identity

Each registered server has:

- stable UUID and account-unique logical name;
- display name, description and owning team;
- project and environment availability;
- trust tier: unverified, partner, internal or accredited;
- lifecycle: draft, in review, approved, deprecated, quarantined or retired;
- transport endpoints: Streamable HTTP, legacy SSE or local bridge;
- typed provider connection reference for OAuth, API key or mTLS;
- publisher, provenance, package/container digest and optional SBOM/signature;
- health state and last successful discovery;
- current approved capability snapshot.

Q-017 is resolved by this draft as follows: the next AAP descriptor revision requires a
stable `name` beside every MCP server URL. Existing descriptors retain URL/name heuristics
only as a visibly degraded compatibility mode. New releases use exact logical identity.

### Versioned capability discovery

Registration is mutable metadata. Discovery creates an immutable snapshot containing:

- server protocol and capability declarations;
- tools with input/output schema digests;
- resources and resource templates;
- prompts;
- declared MCP annotations;
- canonical manifest digest;
- discovery time, source and discoverer version.

Large schemas are stored as protected object data with bounded metadata and digests in
PostgreSQL. Evidence contains only the approved digest and decision.

MCP annotations such as `readOnlyHint` and `destructiveHint` are untrusted declarations.
They are never the sole basis for an allow decision. Security administrators assign a
verified risk classification and policy remains authoritative.

### Registration and import flows

- Manual registration by an authorized administrator.
- Import from `.cursor/mcp.json`, Claude Desktop or VS Code MCP configuration.
- Import from an AAP descriptor as a draft.
- Promote an observed-only server into a review request.
- Import an external marketplace listing into the private registry.

Every import performs discovery, computes a manifest digest and requires explicit
approval before production use.

### User, team and agent access

Access is grant-based and may target:

- an MCP server;
- an individual tool, resource or prompt pattern;
- account, project, environment or agent scope;
- a member, team, workload credential or immutable agent version;
- a time window or session;
- data classification, region, engagement and resource constraints.

Typical actions are **Discover**, **Use**, **Call**, **Approve call**, **Manage** and
**Quarantine**.

An agent may invoke an MCP tool only when both the agent version and the initiating user
are authorized. Background service agents without a human require an explicitly approved
service grant.

### Human delegation and runtime approval

A trusted application may exchange a human session for a short-lived delegation token
bound to:

- member and account;
- project, environment, session and agent version;
- allowed capability IDs;
- data class and engagement;
- issue time, expiry and policy digest.

The gateway verifies it locally. It cannot grant more authority than the user or agent
already has.

For a conditionally allowed destructive call, the gateway returns an explainable
`approval_required` decision. Approval produces a short-lived, single-purpose token bound
to the exact server, tool signature, normalized resource scope, session and arguments
digest. A retry with changed arguments requires a new decision.

Cursor’s approval card may present this decision, but Cursor does not create the company
authorization.

### Gateway MCP enforcement sequence

```text
authenticate workload and optional delegated user
→ resolve account/project/environment/agent version
→ load signed registry and policy snapshot
→ filter tools/list, resources/list and prompts/list
→ independently authorize every tools/call or read
→ validate pinned server/tool schema and argument shape
→ check resource scope, data class, region, quota and approval
→ lease downstream credentials
→ redact/block prohibited request content before egress
→ forward and enforce response size/content policy
→ emit content-free decision plus correlated OTLP span
```

Filtering discovery is not enough. Every invocation is independently authorized because
a client can call a hidden tool by name.

### Sessions, quotas and result controls

- Redis may hold bounded MCP session routing, replay prevention and rate/concurrency
  counters; it is never the durable registry or audit store.
- Limits may apply per account, project, user, agent, server and tool.
- Tool results have size, secret, content classification and schema controls.
- Protected arguments/results follow Observe capture, encryption and retention policy.
- Evidence never stores tool arguments or results.

### Drift, quarantine and revocation

The system compares:

- descriptor-declared server and snapshot digest;
- registry-approved snapshot;
- signed gateway policy;
- observed server/tool identity and behavior.

A changed tool schema, new tool, annotation mismatch, signature failure, undeclared
server or denied-call spike produces a finding. Policy may warn, require reapproval,
quarantine the server or immediately revoke access. Gateway snapshot refresh distributes
the decision without a control-plane call on every request.

### MCP registry data model

Proposed tables, all tenant-scoped:

```text
mcp_servers
mcp_transport_endpoints
mcp_server_snapshots                 append-only
mcp_tools                            snapshot-owned
mcp_resources                        snapshot-owned
mcp_prompts                          snapshot-owned
mcp_verified_risks
mcp_agent_version_bindings
mcp_server_approvals                 append-only
mcp_revocations                      append-only
mcp_discovery_events                 append-only
runtime_approval_tokens              digest only, short-lived
```

Secrets remain in the connections provider. General member/team grants remain in
`access_grants` using MCP resource types rather than duplicating access tables.

### MCP registry APIs

```text
GET/POST    /v1/mcp-servers
GET/PATCH   /v1/mcp-servers/{id}
POST        /v1/mcp-servers/import-config
GET         /v1/mcp-servers/export-config
POST        /v1/mcp-servers/{id}/discover
GET         /v1/mcp-servers/{id}/snapshots
GET         /v1/mcp-servers/{id}/snapshots/{snapshot_id}
POST        /v1/mcp-servers/{id}/approve
POST        /v1/mcp-servers/{id}/quarantine
POST        /v1/mcp-servers/{id}/retire
GET         /v1/mcp-tools
GET         /v1/mcp-resources
GET         /v1/mcp-prompts
GET/POST    /v1/mcp-servers/{id}/agent-bindings
POST        /v1/runtime-approvals
POST        /v1/runtime-approvals/{id}/decide
```

### MCP configuration export

Given member, project, environment and optional agent, the API computes effective access
and generates Cursor, Claude Desktop and VS Code configuration pointing only to the
gateway. It never exports downstream provider secrets. Export has its own digest so CI
can detect local configuration drift.

## Adjacent registries

### A2A agent registry

The A2A registry owns external/internal Agent Cards, canonical agent identity, endpoint,
card digest, trust tier, skills/capabilities, owner, authentication connection, health
and allowed delegation edges.

Initial scope is discovery, approval and access. The later gateway module supports Agent
Card proxying, `message/send`, streaming, task get/cancel and `contextId` routing.
Agent state remains agent-owned by default. A shared memory vault is a separate,
explicit-custody feature and Redis is not its source of truth.

### Native tool registry

Non-MCP HTTP, gRPC, SQL and function tools need the same stable identity, owner, schema
digest, effect, reversibility, risk, endpoint and access grants. First release registers
and observes them; enforcement requires an egress proxy or trusted runtime integration.

### Data and memory connection registry

Database, vector-store, object-store, SaaS and memory sources require:

- owner and project/environment scope;
- classification and residency;
- read/write capability;
- secret connection reference;
- allowed agents/users;
- retrieval/write telemetry;
- retention and egress policy.

This is later than provider/MCP connections but is tracked because otherwise an agent
could be blocked from a tool while reading the same data through an ungoverned connector.

### Model/provider catalogue

The existing model-routing domain remains authoritative. The redesign adds:

- connection health and commercial owner;
- observed-only model review;
- user/team/agent access;
- stable aliases;
- engagement, residency, data-class, budget and fallback conditions;
- denial and drift views shared with MCP/A2A.

### Prompt, skill, rule and guardrail catalogue

Prompt service and agent composition remain the sources of truth. Access and approval
are added without copying prompt content into the control plane or evidence. Immutable
digests bind approved revisions to agent versions and gateway policy.

## Cross-cutting enterprise controls

These capabilities are part of the master architecture even when their implementation is
later than the first MCP release.

### Policy hierarchy and decision explanation

Policy inputs have a defined precedence:

1. hard platform security invariants;
2. account security policy;
3. client engagement, residency and data-class obligations;
4. project and environment policy;
5. approved immutable agent-version capabilities;
6. member/team/workload grants;
7. short-lived session delegation and approval.

A lower layer may narrow authority but cannot widen a higher-layer deny. Every decision
returns a stable reason code, the denying policy/rule reference, remediation guidance and
a content-free decision digest.

### Budgets, limits and chargeback

Limits apply to LLM tokens/cost, MCP calls, tool calls, A2A tasks and concurrency at
account, project, team, member, agent and connection scope. Redis enforces live counters;
durable usage and policy are stored outside Redis. Actions are warn, throttle, require
approval or deny. Activity and Admin show spend owner, vendor account, forecast and the
member/agent responsible.

Initial release reuses existing gateway rate and budget limits. A later budget domain
adds planned budgets, alerts, chargeback allocation and invoice reconciliation.

### Lifecycle and change management

Every governed resource supports owner, lifecycle, environment promotion, approval,
version/digest, deprecation and revocation. Changes to model deployment, MCP snapshot,
A2A card, tool schema, prompt/skill/rule or provider connection produce a reviewable
change linked to affected agent versions, releases and accreditations.

CI may extract and submit descriptors, but CI cannot approve its own production release.

### Notifications and external security operations

The event model supports:

- in-product attention queue;
- email/webhook notification preferences;
- SIEM/SOAR export over OTLP or a documented webhook envelope;
- alerts for denied-call spikes, new observed tools, credential expiry, failed discovery,
  quarantine, break-glass and policy drift;
- acknowledgement and assignment without inventing a separate incident system initially.

A dedicated incident domain is deferred until findings and Evaluate alerts prove
insufficient.

### Marketplace and discovery

The optional marketplace contains external listings for MCP servers, agents, tools,
skills and templates. Import copies a signed listing into the account registry as a draft.
Marketplace removal or publisher mutation never silently changes an approved account
snapshot. Air-gap installations consume reviewed offline bundles and never phone home.

### Billing, licensing and commercial ownership

- Existing model/MCP/SaaS vendors bill the customer through their connections.
- The platform bills for licensed modules, operated gateway/control plane, retained
  observability and assurance workflows.
- Every connection records commercial owner and optional contract/residency metadata.
- Module entitlements remain an independent gate from user permissions.
- Usage metering may support internal chargeback without turning the product into a model
  token reseller.

### Application and developer integrations

Tracked integrations include:

- OpenAI-compatible model clients;
- provider-native clients where a base URL can be changed;
- Cursor, Claude Code, VS Code and local MCP bridge configuration;
- Python and TypeScript `aap-trace`;
- OTLP collectors;
- CI descriptor extraction and release submission;
- webhooks/SIEM;
- later Terraform/Kubernetes custom resources for large estates.

Each integration documents exactly which paths are controlled and marks unsupported
vendor-hosted traffic unknown.

## Control-plane domain ownership

New domains are proposed; exact layer order requires an ADR before implementation.

| Concern | Owner |
|---|---|
| Human profile and identity links | `members` |
| Teams, roles, grants and effective access | `access` |
| Provider/MCP/A2A/data secret metadata and provider calls | `connections` |
| MCP server identity, snapshots, risk and bindings | `mcp_registry` |
| A2A cards and delegation edges | `a2a_registry` |
| Security and access audit | `security_audit` |
| Projects and Platform Keys | existing `workload_identity` |
| Models, routes and signed enforcement bundle | existing `model_routing`, expanded as gateway policy compiler |
| Actual execution and user activity | Observe |
| Declared-versus-observed reconciliation | existing `composition` |
| Findings and proof | existing `assurance` and `evidence` |

`mcp_registry` is an approved-catalogue owner. `operations` remains observed inventory.
Neither reads the other’s tables.

## Authorization and approval flows

### Agent access

A human receives a role at account, project, environment or agent scope. Common presets:

- View an agent.
- Run an agent.
- Edit and test an agent.
- Publish a version.
- Approve a version.
- Manage runtime credentials.

The simple UI uses these presets. The backend stores explicit permissions and scope.

### Provider connection use

Creating a connection and using it are separate permissions. A security administrator
may create a company Anthropic connection and grant “use” to three production agents
without giving developers the underlying key.

### Approval

Production publication, materiality adjudication and accreditation approval use verified
actors. The service layer enforces approver separation. High-risk accounts may require
two approvers.

### Access request

When a user lacks access, the product offers **Request access**, not a dead 403.
The request states resource, requested role, duration and reason. Approval produces an
audited access grant.

### Break glass

Emergency access requires a reason, ticket, expiry and elevated permission. Secret reveal
and protected payload access are separately controlled. Every use emits a high-severity
audit event; dual approval is available for enterprise mode.

## Backend domains and APIs

Proposed new control-plane domains:

1. `members`: profile and verified identity linkage;
2. `access`: teams, roles, grants, group mappings and authorization;
3. `connections`: provider connection metadata and secret-provider orchestration;
4. `mcp_registry`: MCP identity, discovery snapshots, risk, approvals and bindings;
5. `a2a_registry`: Agent Cards, trust and delegation edges, implemented later;
6. `security_audit`: append-only identity/access/credential events.

`workload_identity` remains the owner of projects and platform workload credentials.
`model_routing` references connection IDs through its service boundary and continues to
compile signed gateway snapshots.

### Migration and compatibility order

Migration IDs are not assigned before Q-024 approval. The dependency order is:

1. non-superuser runtime database role and grants;
2. members and member identities;
3. teams, roles and access grants;
4. security audit events and verified actor references;
5. connection metadata and secret-version references;
6. MCP registry, immutable snapshots and bindings;
7. optional A2A registry;
8. gateway policy snapshot revision and correlation columns.

All revisions are additive and hand-written. Existing `org_id` values remain. Existing
descriptors and gateway snapshot revision 1 remain readable during the compatibility
window.

### Cross-domain events

Durable outbox events coordinate owners without table sharing:

```text
member.disabled
access.grant.changed
connection.rotated
connection.disabled
mcp.server.approved
mcp.snapshot.created
mcp.server.quarantined
mcp.binding.changed
a2a.agent.approved
agent.version.published
gateway.policy.compiled
```

Consumers are idempotent. Registry or access changes trigger policy recompilation,
Observe correlation refresh and affected-agent analysis through versioned contracts.

Proposed human APIs:

```text
GET/PATCH  /v1/me
GET        /v1/members
GET/PATCH  /v1/members/{member_id}
GET/POST   /v1/teams
GET/PUT    /v1/teams/{team_id}/members
GET        /v1/roles
GET/POST   /v1/access-grants
DELETE     /v1/access-grants/{grant_id}
GET/POST   /v1/access-requests
POST       /v1/access-requests/{id}/approve
GET/POST   /v1/provider-connections
POST       /v1/provider-connections/{id}/rotate
POST       /v1/provider-connections/{id}/test
POST       /v1/provider-connections/{id}/disable
GET        /v1/security-audit-events
```

The existing workload-credential APIs remain, with role checks and a clearer console
name: **Platform keys**.

Proposed internal API:

```text
POST /internal/v1/provider-connections/{id}/lease
```

Only an authenticated gateway identity can call it. A lease is short-lived, audited and
never enters the signed router snapshot.

The gateway signed-policy contract requires a backward-compatible revision that adds:

- canonical member/team delegation claims;
- MCP servers, approved snapshots and capability patterns;
- A2A agents and allowed delegation edges;
- connection references, never secret values;
- data classification, residency and egress rules;
- limits, approval requirements and policy digest.

Old gateways continue to read revision 1 for LLM-only operation. MCP/A2A enforcement
requires the new revision. Readers ship before writers and mixed-version tests are
mandatory.

## Console information architecture

The current console has too many peer destinations and duplicates runtime concepts. The
new shell has six stable destinations:

### Home

Personalized attention queue:

- approvals waiting for me;
- blocked or unusual activity;
- expiring keys and unhealthy connections;
- agents I own;
- recent user and agent activity.

### Agents

- Agent inventory.
- Agent detail: Overview, Activity, Access, Versions, Assurance.
- Prompts and evaluations are reached from the agent context.
- Runtime keys and allowed connections are visible under Access.

### Activity

- Executions.
- Sessions.
- People activity.
- Tools and MCP.
- Models, cost and latency.
- Live activity.

The same execution shows the initiating person and every effective agent/service actor.

### Control

- Provider connections.
- Models and routing.
- MCP registry: Servers, Tools, Resources, Prompts, Access, Snapshots and Audit.
- A2A agents.
- Native tools.
- Data and memory connections.
- Platform keys.
- Runtime policies.

### Assurance

- Changes and releases.
- Approvals and accreditations.
- Findings.
- Evidence.
- Evaluations and stress testing.
- Clients, engagements and service levels.

### Admin

Visible only to authorized roles:

- People.
- Teams.
- Roles and access.
- Access requests.
- Projects and environments.
- Security audit.
- Account and identity provider.
- Modules and licensing.

The user avatar opens Profile, Preferences, Developer connections when enabled, Help
and Sign out. The account identity is not a persistent navigation destination for
ordinary users.

## Core screens

### My profile

- Verified name, email and identity provider.
- Team and role summary.
- Default project and preferences.
- Sessions and recent activity.
- Personal developer connections only when enabled.

### People

- Search/filter by team, role, project, status and activity.
- Row shows identity, effective access, agents used, last activity and risk attention.
- Detail: Overview, Activity, Agents, Access, Credentials metadata, Audit.

### Roles and access

- Start with built-in role cards and a scope browser.
- Effective-access inspector explains every grant source.
- Grant dialog asks role, resource scope, expiry and reason.
- Dangerous permissions use explicit confirmation and approver separation.

### Provider connections

- Cards/list grouped by provider and scope.
- State: healthy, degraded, expired, disabled.
- Add flow: provider → authentication → scope → test → review.
- Never redisplay a secret.
- Connection detail shows assigned agents/routes, usage, rotation and audit.

### Platform keys

- Project/environment/agent scope.
- Issue, copy once, rotate, revoke.
- Last used and affected integrations.
- Clear distinction from provider credentials.

### Agent access

- Humans and teams who may view, run, edit, publish or approve.
- Provider/model/tool/MCP/A2A capabilities available to that agent version.
- Differences between declared, approved and observed behavior.

### MCP registry

- Server list grouped by lifecycle, trust, health, environment and owner.
- Registration/import wizard with discovery and connection selection.
- Detail sections: Overview, Endpoints, Capabilities, Snapshots, Access, Agents, Activity
  and Audit.
- Capability diff highlights added/removed tools and schema/annotation changes.
- Effective-access inspector answers why a specific person/agent can or cannot call a
  specific tool.
- Config export generates gateway-only Cursor, Claude Desktop and VS Code configuration.
- Observed-only inventory links to a reviewed promotion workflow.

### Integrations overview

A single Control landing page shows Models, MCP, A2A, Native tools and Data connections
without merging their schemas. Each category shows health, approved/observed drift,
affected agents, owners and urgent actions.

## Visual and interaction direction

“Apple-like” means disciplined product behavior, not copying Apple branding:

- quiet chrome and generous whitespace;
- one dominant action per page;
- progressive disclosure instead of dense configuration forms;
- persistent context and direct-manipulation split views;
- clear hierarchy using typography before borders or color;
- semantic color only for state and risk;
- brief, human explanations for every policy denial;
- immediate optimistic feedback only where rollback is safe;
- restrained 150–200 ms motion with reduced-motion support;
- complete keyboard navigation and visible focus;
- WCAG 2.2 AA contrast and interaction targets;
- responsive rail, tables and execution inspector;
- no wall of equal cards, decorative gradients or dashboard clutter.

The existing token system, charts, React Router, TanStack Query and Cytoscape remain.
No new UI dependency is approved by this plan.

## Delivery plan

One vertical slice is completed and certified before the next. Time ranges assume one
developer and include backend, contract, UI and tests.

### Phase 0 — Architecture freeze and certification baseline (3–5 days)

- Approve Q-024 terminology, identity, role, registry and credential decisions.
- Finish the relevant Phase 13 clean-volume/recovery baseline.
- Inventory every mutation endpoint and assign its required permission.
- Freeze API naming and migration order.
- Produce threat model for login, grants, secrets and gateway leases.

**Exit:** approved ADRs, permission matrix, ERD, route map and no unresolved destructive
tenant change.

### Phase 1 — Real identity and database isolation (7–10 days)

- OIDC Authorization Code with PKCE.
- Non-superuser application database role; prove RLS works.
- `GET /v1/me`.
- Members and member identities.
- Remove production dependence on `OrgGate` and `X-Org-Id`.
- Bootstrap flow for the first account owner and identity binding.

**Exit:** clean SaaS login, BYOC/air-gap single-account login and cross-account isolation
tests pass.

### Phase 2 — Authorization and actor integrity (10–12 days)

- Roles, permissions, teams and scoped grants.
- Central `authorize` dependency plus service-level workflow checks.
- Replace caller-supplied audit actor fields with verified actors.
- Protect the highest-risk routes first: role management, policy publish, release,
  accreditation, findings, router publish, protected content and key issuance.
- Security audit events for identity and authorization.

**Exit:** deny-by-default mutation suite, approver-separation tests and effective-access
explanations pass.

### Phase 3 — New application shell and directory (8–10 days)

- New six-destination navigation and route aliases.
- Profile, People, Teams, Roles and Access Requests.
- Permission-aware controls; server remains authoritative.
- Personalized Home attention queue.
- Keep legacy routes as redirects until all bookmarks and links migrate.

**Exit:** user can sign in, find a person, understand effective access, grant/revoke it
and see the audit record.

### Phase 4 — Provider connection vault (10–15 days)

- Connections metadata and secret-provider abstraction.
- KMS/secret-manager providers for deployment modes.
- Create, test, rotate and disable connections.
- Gateway secret lease contract with bounded in-memory cache.
- Provider Connections console.
- Personal development connections behind an account policy flag.

**Exit:** no provider plaintext appears in PostgreSQL, logs, OpenAPI responses, evidence,
ClickHouse or signed snapshots; rotation works without agent downtime.

### Phase 5 — Platform keys, agent access and MCP registry foundation (12–15 days)

- Redesign existing workload credentials as Platform Keys.
- Issue/copy-once/rotate/revoke flows.
- Agent- and environment-scoped grants.
- Agent Access screen combining people, teams, models, tools, MCP and A2A permissions.
- Last-used and affected-agent analysis.
- MCP registry domain, stable identity, lifecycle, manual registration and ownership.
- Descriptor binding using stable logical names; legacy heuristic remains visible.
- MCP server list/detail and access-grant UI.

**Exit:** an admin can provision an agent without sharing a provider key, grant a person
and agent version access to an approved MCP server, and revoke the Platform Key.

### Phase 6 — MCP discovery, snapshots and unified activity (12–15 days)

- People directory links to Observe observed users.
- Bind trusted telemetry identities to platform members.
- Person → session → execution → agent/tool/model navigation.
- Coverage indicators on every aggregate.
- User and agent cost, denials, tool/MCP activity and risk attention.
- Server discovery through a leased connection.
- Immutable tools/resources/prompts snapshots and manifest digest.
- Snapshot diff, verified risk, approval and descriptor pinning.
- Observed-only MCP promotion and declared/approved/observed reconciliation.

**Exit:** the console can answer “what did this person and their agents do?”, show which
approved MCP snapshot was expected and identify drift without claiming visibility into
uninstrumented Cursor/Claude traffic.

### Phase 7 — Gateway MCP policy and runtime approval integration (15–20 days)

- Signed policy IR includes member/team delegation and agent-version capabilities.
- Go gateway supports MCP Streamable HTTP tools discovery/invocation first.
- MCP authorization uses the same human/workload/agent-version model.
- `tools/list` is filtered and every `tools/call` is independently authorized.
- Local stdio bridge and Cursor/Claude/VS Code configuration export.
- Request-access and approval decision integration.
- Company denial reason shown in clients without relying on Cursor’s local auto-review.
- Content-free decisions flow to Observe and evidence.
- Quarantine/revoke, response controls, quotas and bypass-detection telemetry.

**Exit:** the same call is denied consistently in Cursor-through-gateway, CI and
production, with one explainable decision record; changing arguments invalidates a
single-purpose approval.

### Phase 8 — A2A and adjacent registry foundation (10–15 days)

- A2A Agent Card registry, ownership, trust, access and health.
- Allowed delegation edges and agent-version binding.
- Native tool and data/memory connection metadata foundations.
- Model, MCP, A2A and connection overview in Control.
- A2A mediation remains separately gated behind Q-023 and protocol certification.

**Exit:** every resource class in the AAP descriptor has a canonical or explicitly
deferred control-plane owner; no UI label exists without a backend contract.

### Phase 9 — Polish and production certification (7–10 days)

- Responsive and keyboard-complete shell.
- Accessibility audit.
- Performance budgets and route-level code splitting.
- Secret/key abuse tests, session recovery and break-glass certification.
- Upgrade and rollback from the current schema.
- Deterministic end-to-end demo for admin, developer, approver and auditor personas.
- MCP registration → grant → config export → allow/deny → Observe → finding/evidence demo.

**Exit:** fresh deploy, upgrade, recovery, load, security and browser suites pass.

## Estimated delivery

- Identity + RBAC usable vertical release: approximately 4–5 weeks.
- Connections + platform keys + redesigned admin: approximately 8–10 weeks cumulative.
- Unified people/agent activity and LLM/MCP gateway enforcement: approximately 18–24
  weeks
  cumulative for one developer.

A visual-only redesign before identity, RBAC and contract work would create attractive
screens backed by insecure behavior. It is explicitly not the delivery order.

## Verification requirements

Every phase must include:

- unit and real-PostgreSQL integration tests;
- cross-account and project/agent-scope isolation tests;
- non-superuser RLS execution;
- OpenAPI regeneration and typed web client checks;
- web lint, typecheck, build and browser flows;
- no-secret corpus tests across logs, evidence, Observe and API responses;
- workload/human token confusion tests;
- approver-of-record and actor-integrity tests;
- SaaS, BYOC and air-gap configuration validation;
- gateway mixed-snapshot compatibility when the policy contract changes.

## Decisions needed before implementation

1. Approve **Account** as the customer-visible term while retaining `org_id` internally.
2. Approve platform-managed roles with optional IdP-group synchronization.
3. Approve the initial built-in roles and separate approver-of-record.
4. Approve provider connections as admin-managed by default.
5. Approve personal BYOK only for development/playground and disabled by default.
6. Approve Platform Keys as the UI name for `aap_wk_*` workload credentials.
7. Approve the six-destination console information architecture.
8. Approve the delivery order: identity/RBAC before visual migration and gateway expansion.
9. Approve registry/inventory/marketplace as separate product surfaces.
10. Approve stable MCP logical names in the next descriptor revision and legacy-only URL
    heuristics.
11. Approve MCP registry and tool-level grants in the first licensed release.
12. Approve Streamable HTTP tools as the first gateway MCP enforcement slice, with local
    stdio bridge and broader MCP resources/prompts afterward.
13. Approve A2A registry before A2A shared-state custody.
14. Approve semantic cache only after identity, policy-aware keys and measured demand.

