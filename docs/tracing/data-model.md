# Agent Observability Data Model

## Hierarchy

```text
Organization -> Project -> Environment -> Agent -> Agent Version
Organization -> Project -> Session -> Agent Execution -> Observation -> Event
Agent Execution -> Execution Link
Observation -> Payload Reference -> encrypted object
```

An agent execution is the canonical trace root. A session groups user-visible work,
including retries, replays, evaluations, and multiple cooperating agents.

## Agent execution

`observe.agent_executions` stores searchable execution metadata:

- identity: execution, trace, root span, parent execution/trace;
- placement: organization, project, environment, session;
- agent: ID, name, version, framework, runtime and deployment;
- invocation: initiating user, effective actor, source, application, client, request;
- source control: repository, branch and commit;
- lifecycle: status, timestamps, live/partial/malformed/cycle flags;
- aggregates: typed operation counts, errors, retries, tokens, cost and sample rate;
- lineage: replay origin and parent relationships.

## Observations

Every observation has a stable span ID, parent span ID, trace ID, type, operation name,
status, timestamps, attributes, and events. Supported types include:

`agent`, `node`, `generation`, `tool`, `sdk`, `retrieval`, `chain`, `http`,
`database`, `state_transition`, `event`, `evaluation`, `error`, `retry`, `checkpoint`,
`human_approval`, `guardrail`, `memory`, `embedding`, `mcp`, and `a2a`.

Input/output content is not stored in ClickHouse. Content attributes become size/digest
metadata plus an encrypted payload reference according to project capture policy.

## Relationships

`observe.execution_links` stores de-duplicated outgoing relationships:

- `parent_execution`;
- `replay_of`;
- `a2a_invocation`;
- `mcp_peer`.

The query API returns each link with an incoming/outgoing direction so the UI can
expand across agents and traces.

## Retention and isolation

Payload references carry a retention deadline, legal-hold state, deletion timestamp,
redaction state, digest, size, and encryption-key reference. Expired objects are deleted
only when no reference to the shared object remains active or held.

All PostgreSQL tables containing both `organization_id` and `project_id` have forced
row-level security. Query and ingest transactions set tenant context; background workers
use an explicit worker context.
