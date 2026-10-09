"""Operations schemas — runs, cost and tool usage at the boundary.

Money is always ``cost_micros``, an integer count of millionths of a USD. It is never a
float and never a formatted string, in either direction. Summing floating-point money
over a month of runs produces a total that depends on the order of summation, and a
currency-formatted string in an API forces every consumer to parse it back. The console
has one helper that turns micros into something a person reads, and that is the only
place the conversion happens.

Nothing here can carry a prompt, a completion or a tool argument (AGENTS.md rule 5).
``error_kind`` is a classification such as ``tool_timeout``, bounded to 64 characters by
the column behind it, and there is no free-text field to put a model's output in.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domains.registry.schemas import LifecycleState


class RunOutcome(StrEnum):
    """How a run ended, or that it has not.

    ``refused`` is separate from ``failed`` on purpose. An agent declining to act,
    because a guardrail fired or a policy denied it, is the system working as designed;
    counting it as a failure makes a well-governed estate look broken and gives people a
    reason to turn the guardrail off.
    """

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REFUSED = "refused"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


class StepKind(StrEnum):
    """What one row in ``run_steps`` represents — a graph node, a model call, a tool."""

    NODE = "node"
    LLM = "llm"
    TOOL = "tool"
    MCP_TOOL = "mcp_tool"
    RETRIEVAL = "retrieval"
    GUARDRAIL = "guardrail"
    HANDOFF = "handoff"
    SUB_AGENT = "sub_agent"


_TOOL_KINDS = frozenset({StepKind.TOOL, StepKind.MCP_TOOL, StepKind.RETRIEVAL})


class ToolSurface(StrEnum):
    """Where a tool came from.

    ``MCP`` is the one this product cares most about: an MCP server is a dependency with
    its own supply chain, and the tools it exposes can change without the agent's
    descriptor changing at all.
    """

    MCP = "mcp"
    NATIVE = "native"
    RETRIEVAL = "retrieval"
    SUB_AGENT = "sub_agent"
    HANDOFF = "handoff"


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------


class StepReport(BaseModel):
    """One step inside a run, as a LangGraph callback would report it."""

    seq: int = Field(ge=0)
    parent_seq: int | None = None
    kind: StepKind
    name: str = Field(min_length=1, max_length=128)
    surface: ToolSurface | None = None
    server_name: str = Field(default="", max_length=128)
    started_at: datetime
    ended_at: datetime | None = None
    outcome: RunOutcome = RunOutcome.RUNNING
    attempt: int = Field(default=1, ge=1)
    model: str | None = Field(default=None, max_length=128)
    tokens_in: int = Field(default=0, ge=0)
    tokens_out: int = Field(default=0, ge=0)
    cost_micros: int = Field(default=0, ge=0)
    error_kind: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def _terminal_steps_have_an_end(self) -> StepReport:
        finished = self.outcome is not RunOutcome.RUNNING
        if finished and self.ended_at is None:
            raise ValueError("a step that has finished must carry ended_at")
        if not finished and self.ended_at is not None:
            raise ValueError("a step with ended_at must report a terminal outcome")
        if self.ended_at is not None and self.ended_at < self.started_at:
            raise ValueError("ended_at cannot precede started_at")
        return self

    @model_validator(mode="after")
    def _parent_is_not_self(self) -> StepReport:
        if self.parent_seq is not None and self.parent_seq == self.seq:
            raise ValueError("parent_seq must differ from seq")
        return self

    @model_validator(mode="after")
    def _surface_matches_kind(self) -> StepReport:
        needs_surface = self.kind in _TOOL_KINDS
        if needs_surface and self.surface is None:
            raise ValueError("surface is required for tool, mcp_tool and retrieval steps")
        if not needs_surface and self.surface is not None:
            raise ValueError("surface must be null unless the step is a tool call")
        return self

    @model_validator(mode="after")
    def _mcp_names_its_server(self) -> StepReport:
        if self.kind is StepKind.MCP_TOOL and not self.server_name.strip():
            raise ValueError("server_name is required for mcp_tool steps")
        return self


class ToolCallReport(BaseModel):
    """Tool activity from one run, already counted.

    A run reports its tool calls as totals rather than individually, because that is
    what the daily buckets store and what every screen asks for. A LangGraph callback
    handler naturally accumulates exactly this.
    """

    surface: ToolSurface
    server_name: str = Field(default="", max_length=128)
    tool_name: str = Field(min_length=1, max_length=128)

    calls: int = Field(default=1, ge=0)
    errors: int = Field(default=0, ge=0)
    denied: int = Field(default=0, ge=0)

    total_duration_ms: int = Field(default=0, ge=0)
    max_duration_ms: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _outcomes_fit_within_calls(self) -> ToolCallReport:
        if self.errors + self.denied > self.calls:
            raise ValueError("errors + denied cannot exceed calls")
        return self


class RunReport(BaseModel):
    """One run, as an SDK or collector reports it.

    The same report is used to open a run and to close it: send it with no ``ended_at``
    when work starts, then again with the outcome when it finishes. ``run_id`` is chosen
    by the client so the second report can find the first, and so a retried delivery is
    recognised rather than counted twice.

    An agent is named either by ``agent_id`` or by ``agent_urn``. The URN is what an SDK
    knows — it comes from configuration next to the agent's own code — whereas the id is
    a database key the agent has no reason to hold.
    """

    run_id: UUID | None = None

    agent_id: UUID | None = None
    agent_urn: str | None = Field(default=None, max_length=256)
    agent_version_id: UUID | None = None

    environment: LifecycleState = LifecycleState.DEV

    started_at: datetime
    ended_at: datetime | None = None
    outcome: RunOutcome = RunOutcome.RUNNING

    step_count: int = Field(default=0, ge=0)
    tool_call_count: int = Field(default=0, ge=0)
    retry_count: int = Field(default=0, ge=0)

    model: str | None = Field(default=None, max_length=128)
    tokens_in: int = Field(default=0, ge=0)
    tokens_out: int = Field(default=0, ge=0)
    cost_micros: int = Field(default=0, ge=0)

    escalated: bool = False
    guardrail_blocks: int = Field(default=0, ge=0)

    error_kind: str | None = Field(default=None, max_length=64)
    trace_id: str | None = Field(default=None, max_length=128)

    reported_by: str = Field(default="sdk", max_length=32)

    tools: list[ToolCallReport] = Field(default_factory=list)
    steps: list[StepReport] = Field(default_factory=list, max_length=1000)

    @model_validator(mode="after")
    def _step_seqs_are_unique_within_the_report(self) -> RunReport:
        seen: set[int] = set()
        for step in self.steps:
            if step.seq in seen:
                raise ValueError(f"duplicate step seq {step.seq} within one report")
            seen.add(step.seq)
        return self

    @model_validator(mode="after")
    def _identifies_an_agent(self) -> RunReport:
        if self.agent_id is None and not self.agent_urn:
            raise ValueError("a run must name an agent by agent_id or agent_urn")
        return self

    @model_validator(mode="after")
    def _terminal_runs_have_an_end(self) -> RunReport:
        """Mirrors the `agent_runs_terminal_has_end` constraint, so a bad report is a 422
        naming the field rather than a 500 out of the database."""
        finished = self.outcome is not RunOutcome.RUNNING
        if finished and self.ended_at is None:
            raise ValueError("a run that has finished must carry ended_at")
        if not finished and self.ended_at is not None:
            raise ValueError("a run with ended_at must report a terminal outcome")
        if self.ended_at is not None and self.ended_at < self.started_at:
            raise ValueError("ended_at cannot precede started_at")
        return self


class RunBatch(BaseModel):
    """Runs arrive in batches because a collector buffers them.

    The cap exists so one request cannot hold a transaction open long enough to matter;
    a reporter with more than this has more than one request to make.
    """

    runs: list[RunReport] = Field(min_length=1, max_length=500)


class IngestResult(BaseModel):
    opened: int = 0
    closed: int = 0
    ignored: int = 0
    tool_buckets: int = 0
    steps: int = 0
    unknown_agents: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


class RunRow(BaseModel):
    """One run for a list view, carrying enough about its agent to render a row."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    agent_id: UUID
    agent_display_name: str
    agent_urn: str

    environment: LifecycleState
    started_at: datetime
    ended_at: datetime | None
    duration_ms: int | None
    outcome: RunOutcome

    step_count: int
    tool_call_count: int
    retry_count: int

    model: str | None
    tokens_in: int
    tokens_out: int
    cost_micros: int

    escalated: bool
    guardrail_blocks: int
    error_kind: str | None
    trace_id: str | None


class RunPage(BaseModel):
    items: list[RunRow]
    total: int
    limit: int
    offset: int


class StepRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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
    run: RunRow
    steps: list[StepRow]
    self_ms_by_seq: dict[int, int]
    critical_path: list[int]
    steps_truncated: bool


class GraphNodeStat(BaseModel):
    name: str
    kind: StepKind
    runs: int
    executions: int
    failures: int
    p50_duration_ms: int
    p95_duration_ms: int
    cost_micros: int
    tools: list[str]


class GraphEdgeStat(BaseModel):
    from_node: str
    to_node: str
    traversals: int
    failures: int


class ObservedGraph(BaseModel):
    agent_id: UUID
    window_days: int
    nodes: list[GraphNodeStat]
    edges: list[GraphEdgeStat]
    entry_nodes: list[str]
    terminal_nodes: list[str]


class ActivitySeries(BaseModel):
    """Runs per day, split by environment.

    Parallel arrays rather than a list of objects: every entry in ``days`` lines up with
    the same index in each environment's list, which is the shape a chart wants and
    avoids sending the date once per series.
    """

    days: list[date] = Field(default_factory=list)
    by_environment: dict[str, list[int]] = Field(default_factory=dict)
    totals: list[int] = Field(default_factory=list)
    failures: list[int] = Field(default_factory=list)


class CostDay(BaseModel):
    day: date
    cost_micros: int
    tokens_in: int
    tokens_out: int
    runs: int


class CostSlice(BaseModel):
    """Cost attributed to one thing — a model, an agent, an environment."""

    label: str
    cost_micros: int
    tokens: int
    runs: int
    share_pct: float


class CostReport(BaseModel):
    window_days: int
    total_cost_micros: int = 0
    total_tokens: int = 0
    total_runs: int = 0

    # The same window immediately before this one, so the console can show a change
    # without asking twice or doing date arithmetic of its own.
    previous_cost_micros: int = 0

    by_day: list[CostDay] = Field(default_factory=list)
    by_model: list[CostSlice] = Field(default_factory=list)
    by_agent: list[CostSlice] = Field(default_factory=list)
    by_environment: list[CostSlice] = Field(default_factory=list)


class ToolRow(BaseModel):
    """One tool, aggregated across every agent that called it in the window."""

    surface: ToolSurface
    server_name: str
    tool_name: str

    agents: int
    calls: int
    errors: int
    denied: int
    error_rate_pct: float
    mean_duration_ms: int
    max_duration_ms: int

    # Whether every agent that called this tool declares it. Observed-but-undeclared is
    # the finding this product exists to surface: something is being invoked that the
    # calling agent's approved descriptor never mentioned.
    declared: bool
    # How many of the calling agents have not declared it, so the console can say "3 of
    # 9 agents" rather than only yes or no.
    undeclared_agents: int = 0


class ToolInventory(BaseModel):
    window_days: int
    items: list[ToolRow] = Field(default_factory=list)
    mcp_servers: int = 0
    undeclared: int = 0


class McpServerRow(BaseModel):
    """One MCP server, with everything the estate called through it.

    Reported separately from the tool list because the server is the thing somebody
    owns, patches and can revoke. When an MCP server misbehaves the action is at this
    level — disconnect it, pin it, ask its operator — not at the level of one tool.
    """

    server_name: str
    tools: int
    agents: int
    calls: int
    errors: int
    denied: int
    error_rate_pct: float
    mean_duration_ms: int
    last_seen_at: datetime | None = None

    declared: bool
    undeclared_agents: int = 0
    tool_names: list[str] = Field(default_factory=list)


class McpInventory(BaseModel):
    window_days: int
    servers: list[McpServerRow] = Field(default_factory=list)
    total_calls: int = 0
    undeclared_servers: int = 0


class FrameworkShare(BaseModel):
    """How much of the estate is built on one agent framework.

    "Framework" here means LangGraph, CrewAI, the Cursor SDK — the thing the agent's code
    is written against. Not to be confused with the compliance frameworks in
    ``domains/frameworks``, which are ISO 42001 and the like. The column behind this is
    ``agent_versions.runtime_framework``, and the API path says ``runtime`` for the same
    reason.
    """

    framework: str
    agents: int
    runs: int
    share_pct: float


class RunOutcomeCount(BaseModel):
    outcome: RunOutcome
    runs: int


class OperationsSnapshot(BaseModel):
    """Everything operations knows about the window, for the console's landing page.

    Composed into the home summary rather than served to the dashboard directly, because
    the dashboard also needs findings, approvals and service levels — and those belong to
    other domains. ``home`` is the only module allowed to know about all of them.
    """

    window_days: int
    generated_at: datetime

    runs_total: int = 0
    runs_previous: int = 0
    runs_failed: int = 0
    runs_refused: int = 0
    running_now: int = 0
    agents_active: int = 0
    escalations: int = 0

    success_rate_pct: float = 100.0
    p50_duration_ms: int = 0
    p95_duration_ms: int = 0

    activity: ActivitySeries = Field(default_factory=ActivitySeries)
    outcomes: list[RunOutcomeCount] = Field(default_factory=list)
    frameworks: list[FrameworkShare] = Field(default_factory=list)
    cost: CostReport = Field(default_factory=lambda: CostReport(window_days=30))
    tools: ToolInventory = Field(default_factory=lambda: ToolInventory(window_days=30))
    recent_runs: list[RunRow] = Field(default_factory=list)


class ErrorKindCount(BaseModel):
    """Why runs failed. A classification, never a message — see `AgentRun.error_kind`."""

    error_kind: str
    runs: int


class AgentOperations(BaseModel):
    """The estate's questions, asked of one agent.

    Deliberately the same aggregates as :class:`OperationsSnapshot` rather than a smaller
    bespoke set: someone looking at a single agent after seeing it on the dashboard is
    checking the same numbers, and a detail page that computes them differently from the
    overview is a page people learn not to trust.
    """

    agent_id: UUID
    window_days: int
    generated_at: datetime

    runs_total: int = 0
    runs_previous: int = 0
    runs_failed: int = 0
    runs_refused: int = 0
    running_now: int = 0
    escalations: int = 0

    success_rate_pct: float = 100.0
    p50_duration_ms: int = 0
    p95_duration_ms: int = 0

    cost_micros: int = 0
    previous_cost_micros: int = 0
    tokens: int = 0

    activity: ActivitySeries = Field(default_factory=ActivitySeries)
    outcomes: list[RunOutcomeCount] = Field(default_factory=list)
    error_kinds: list[ErrorKindCount] = Field(default_factory=list)
    by_model: list[CostSlice] = Field(default_factory=list)
    cost_by_day: list[CostDay] = Field(default_factory=list)
    tools: list[ToolRow] = Field(default_factory=list)
    mcp_servers: list[McpServerRow] = Field(default_factory=list)
    recent_runs: list[RunRow] = Field(default_factory=list)
