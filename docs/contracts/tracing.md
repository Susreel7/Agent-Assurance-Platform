# Contract: run tracing and the observed graph

This file exists so the API and the console can be built at the same time without either
guessing what the other will do. It is the agreement, not documentation of a decision
already made in code. **If you need to depart from it, change this file in the same
commit and say so** — silently drifting is what makes two-sided work fail to meet.

Migration `0009_run_steps` is already written (`services/api/alembic/versions/`) and is
the source of truth for the columns. Read it before implementing.

## Why steps at all

`agent_runs` answers every estate-level question and none of the ones anybody asks once
something breaks: which node failed, what did it call first, where did the four minutes
go, why did it retry. A LangGraph callback handler already receives node-start, node-end,
tool-start, tool-end and LLM-end events and already knows the node name, so nothing here
asks a reporter to derive anything it does not have.

## Enums

`StepKind` — `node`, `llm`, `tool`, `mcp_tool`, `retrieval`, `guardrail`, `handoff`,
`sub_agent`. `tool` and `mcp_tool` are split because the difference is the whole product:
native tools are code the team ships in its own descriptor; MCP tools come from a server
with its own supply chain that can change what it exposes without any descriptor changing.

`RunOutcome` and `ToolSurface` already exist in `domains/operations/schemas.py`. Steps
reuse `RunOutcome` rather than declaring a parallel enum — a step succeeds, fails, is
refused, times out, or is running, meaning the same six things.

## Ingest — extends the existing `POST /v1/operations/runs`

`RunReport` gains one optional field. Everything else about the endpoint is unchanged,
including that it is exempt from the write guard.

```python
class StepReport(BaseModel):
    seq: int                      # >= 0, the reporter's own counter, NOT a time ordering
    parent_seq: int | None = None # the node a tool call happened inside; != seq
    kind: StepKind
    name: str                     # 1..128; node name, tool name, or model, per kind
    surface: ToolSurface | None = None   # required iff kind in {tool, mcp_tool, retrieval}
    server_name: str = ""         # <= 128; required non-empty iff kind == mcp_tool
    started_at: datetime
    ended_at: datetime | None = None     # null iff outcome == running
    outcome: RunOutcome = RunOutcome.RUNNING
    attempt: int = 1              # >= 1; distinguishes a retry from a loop iteration
    model: str | None = None      # <= 128
    tokens_in: int = 0
    tokens_out: int = 0
    cost_micros: int = 0          # integer millionths of USD, never a float
    error_kind: str | None = None # <= 64; a classification, never a message

class RunReport(BaseModel):
    ...                           # unchanged
    steps: list[StepReport] = []  # max 1000 per run
```

Validation mirrors the database constraints so a bad report is a 422 naming the field
rather than a 500 out of Postgres. That means all of: the terminal/`ended_at` biconditional,
`ended_at >= started_at`, the surface-matches-kind rule, the MCP-names-its-server rule,
`parent_seq != seq`, and duplicate `seq` within one report.

`IngestResult` gains `steps: int` — how many step rows were written.

**Replay safety.** Upsert on `(org_id, run_id, seq, started_at)`, guarded by
`WHERE outcome = 'running'` exactly as runs are, so a redelivered terminal step is ignored
rather than failing the batch it arrived in. Collapse duplicate keys within one batch
before the statement: a single `ON CONFLICT` cannot hit the same row twice.

`duration_ms` is computed from the reported timestamps, never taken from the reporter —
two SDKs measuring it differently would make latency incomparable across the estate.

## Read — run detail

```
GET /v1/operations/runs/{run_id}   ->  200 RunDetail | 404
```

404 here is correct, unlike the per-agent endpoint: an unknown run id is a broken link,
not a real state.

```python
class StepRow(BaseModel):
    id: UUID
    seq: int
    parent_seq: int | None
    kind: StepKind
    name: str
    surface: ToolSurface | None
    server_name: str
    started_at: datetime
    ended_at: datetime | None
    duration_ms: int | None
    outcome: RunOutcome
    attempt: int
    model: str | None
    tokens_in: int
    tokens_out: int
    cost_micros: int
    error_kind: str | None

class RunDetail(BaseModel):
    run: RunRow                   # the existing schema, unchanged
    steps: list[StepRow]          # ordered by seq
    # Derived server-side so the console does not compute a number the API could
    # disagree with later. Self-time is a step's duration minus its children's, which
    # is the only figure that tells you where time actually went in a nested trace.
    self_ms_by_seq: dict[int, int]
    critical_path: list[int]      # seqs, the chain that determined total duration
    steps_truncated: bool         # a run with more steps than we return
```

Steps come back ordered by `seq`. The console renders the waterfall from
`parent_seq`; it does not re-sort by time, because concurrent graph branches start in the
same millisecond and time-ordering would shuffle them differently on every read.

## Read — observed graph

```
GET /v1/operations/agents/{agent_id}/graph?days=30  ->  200 ObservedGraph
```

No 404, matching the existing per-agent operations endpoint: an agent registered this
morning has an empty graph, and that is the honest answer.

This is the LangGraph topology **as observed**, derived from consecutive `node` steps
within each run. It is deliberately not stored in `graph_nodes`/`graph_edges` — that table
is the inter-agent dependency graph used for blast radius, and one table meaning both
would be a permanent source of confusion.

```python
class GraphNodeStat(BaseModel):
    name: str
    kind: StepKind
    runs: int                     # distinct runs that executed it
    executions: int               # including retries, so executions >= runs
    failures: int
    p50_duration_ms: int
    p95_duration_ms: int
    cost_micros: int
    tools: list[str]              # tool and MCP names called inside this node

class GraphEdgeStat(BaseModel):
    from_node: str
    to_node: str
    traversals: int
    failures: int                 # traversals whose destination failed

class ObservedGraph(BaseModel):
    agent_id: UUID
    window_days: int
    nodes: list[GraphNodeStat]
    edges: list[GraphEdgeStat]
    entry_nodes: list[str]        # first node of a run
    terminal_nodes: list[str]     # last node of a run
```

Percentiles skip null durations rather than treating an in-flight step as instantaneous.

## Console

Both screens live under `services/web/src/features/operations/`.

**`RunDetailScreen`** at `/runs/:runId`. Rows in the existing `RunsScreen` become links to
it. A trace waterfall: one row per step, indented by `parent_seq`, bar offset and width
from the step's own start and duration against the run's span, coloured by outcome and
`kind`. Each row shows name, duration, self-time, model, tokens, cost and error kind. A
failed run opens with the failing step in view rather than at the top.

**Observed graph** on the agent detail screen. Reuse the existing Cytoscape `GraphCanvas`
rather than adding a second graph library; size nodes by executions and weight edges by
traversals, and let a node's colour carry its failure rate.

Both need entries in `api/types.ts`, `api/queries.ts`, and `mocks/handlers.ts` so the
console still works in mock mode with `VITE_USE_MOCKS=1`.

## Out of scope here

Anything a reporter needs in order to *authenticate*. The ingest endpoint currently
accepts the development org header, which works on a local stack and nowhere else. The
machine-credential question is open and recorded in `PROJECT_STATE.md`; do not invent an
answer to it in passing.
