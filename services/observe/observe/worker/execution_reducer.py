"""Reduce spans and lifecycle events into agent_executions and execution_index rows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from observe.worker import normalizer

TERMINAL_STATUSES = frozenset(
    {
        "succeeded",
        "failed",
        "timed_out",
        "cancelled",
        "refused",
        "partial",
        "success",
        "error",
    }
)

LIFECYCLE_RUNNING = frozenset(
    {"execution.started", "observation.started", "node.queued", "observation.updated"}
)

EXECUTION_TERMINAL_EVENTS = {
    "execution.completed": "succeeded",
    "execution.failed": "failed",
    "execution.timed_out": "timed_out",
    "execution.cancelled": "cancelled",
    "execution.refused": "refused",
}


def normalize_execution_status(status: str) -> str:

    mapping = {
        "success": "succeeded",
        "error": "failed",
        "open": "open",
        "running": "running",
        "queued": "queued",
    }

    return mapping.get(status, status)


def _outcome_to_status(outcome: str) -> str:

    if outcome == "error":
        return "failed"

    if outcome == "partial":
        return "partial"

    if outcome == "success":
        return "succeeded"

    return "open"


def _find_root_span(
    spans: list[normalizer.NormalizedSpan], root_span_id: str | None
) -> normalizer.NormalizedSpan | None:

    if root_span_id:
        for span in spans:
            if span.span_id == root_span_id:
                return span

    for span in spans:
        if span.observation_type == "agent" or span.kind == "agent":
            return span

    for span in spans:
        if span.parent_span_id is None or span.parent_span_id == "":
            return span

    return spans[0] if spans else None


@dataclass(frozen=True, slots=True)
class ExecutionAggregate:
    execution_id: str

    execution_type: str

    trace_id: str

    root_span_id: str | None

    parent_execution_id: str | None

    parent_trace_id: str | None

    session_id: str | None

    user_session_id: str | None

    environment_id: str | None

    agent_id: str | None

    agent_version_id: str | None

    agent_name: str | None

    initiating_user_id: str | None

    effective_actor_id: str | None

    effective_actor_type: str | None

    invocation_source: str | None

    application_name: str | None

    client_name: str | None

    request_id: str | None

    replay_of_execution_id: str | None

    replay_reason: str | None

    repository_ref: str | None

    branch_ref: str | None

    commit_sha: str | None

    deployment_name: str | None

    region_name: str | None

    runtime_name: str | None

    framework: str | None

    framework_version: str | None

    status: str

    start_time: datetime | None

    end_time: datetime | None

    duration_ms: float | None

    span_count: int

    node_count: int

    generation_count: int

    tool_count: int

    sdk_count: int

    mcp_tool_count: int

    error_count: int

    retry_count: int

    input_tokens: int

    output_tokens: int

    total_cost_micros: int

    provider: str | None

    model: str | None

    sdk_name: str | None

    mcp_server: str | None

    sample_rate: float

    is_live: bool

    is_partial: bool

    is_malformed: bool

    has_cycle: bool

    has_late_data: bool

    capture_level: str | None

    tags: list[str]


def _nano_to_dt(ts: int) -> datetime | None:

    if ts <= 0:
        return None

    sec, nano = divmod(ts, 1_000_000_000)

    return datetime.fromtimestamp(sec, tz=UTC).replace(microsecond=nano // 1000)


def _retry_count(
    spans: list[normalizer.NormalizedSpan],
    events: list[normalizer.NormalizedLogEvent],
) -> int:

    total = 0

    for span in spans:
        if span.observation_type == "retry":
            total += 1

        elif span.retry_attempt > 1:
            total += span.retry_attempt - 1

    return total + sum(
        1
        for event in events
        if event.observation_type == "retry" or event.event_type in {"node.retry", "retry.started"}
    )


def reduce_execution(
    *,
    trace_id: str,
    spans: list[normalizer.NormalizedSpan],
    events: list[normalizer.NormalizedLogEvent],
    malformed: bool,
    has_cycle: bool,
    root_span_id: str | None,
    capture_level: str | None,
) -> ExecutionAggregate:

    execution_id = next(
        (span.execution_id for span in spans if span.execution_id),
        next(
            (event.execution_id for event in events if event.execution_id),
            normalizer.execution_id_for_trace(spans, trace_id),
        ),
    )

    status = "open"

    is_live = True

    is_partial = False

    has_late_data = False

    for ev in sorted(events, key=lambda e: e.event_time_unix_nano):
        if ev.event_type in LIFECYCLE_RUNNING:
            status = "running"

        terminal_status = EXECUTION_TERMINAL_EVENTS.get(ev.event_type)

        if terminal_status is not None:
            is_live = False
            status = terminal_status

    root = _find_root_span(spans, root_span_id)

    if root and root.is_terminal:
        root_status = _outcome_to_status(root.outcome)

        status = root_status

        is_live = False

        is_partial = root.outcome == "partial"

    elif spans and all(s.is_terminal for s in spans):
        if root:
            status = _outcome_to_status(root.outcome)

            is_live = False

            is_partial = root.outcome == "partial"

        else:
            status = "succeeded"

            is_live = False

    status = normalize_execution_status(status)

    starts = [s.start_time_unix_nano for s in spans if s.start_time_unix_nano > 0]

    ends = [s.end_time_unix_nano for s in spans if s.end_time_unix_nano > 0]

    event_times = [e.event_time_unix_nano for e in events if e.event_time_unix_nano > 0]

    start_nano = min(starts + event_times) if (starts or event_times) else 0

    end_nano = max(ends + event_times) if (ends or event_times) else 0

    duration_ms = None

    if start_nano and end_nano and end_nano >= start_nano:
        duration_ms = (end_nano - start_nano) / 1_000_000

    if events and ends and event_times:
        max_end = max(ends)

        if any(t > max_end for t in event_times):
            has_late_data = True

    node_count = sum(1 for s in spans if s.observation_type == "node")

    generation_count = sum(1 for s in spans if s.observation_type == "generation")

    tool_count = sum(1 for s in spans if s.observation_type in {"tool", "mcp"})

    sdk_count = sum(1 for s in spans if s.observation_type == "sdk")

    mcp_tool_count = sum(1 for s in spans if s.observation_type == "mcp")

    error_count = sum(1 for s in spans if s.outcome == "error") + sum(
        1 for e in events if "failed" in e.event_type
    )

    retry_count = _retry_count(spans, events)

    sample = spans[0] if spans else None

    exec_type = (
        sample.execution_type
        if sample and sample.execution_type
        else "agent"
        if any(s.observation_type == "agent" for s in spans)
        else "user_activity"
    )

    if exec_type not in {"agent", "user_activity", "workflow"}:
        exec_type = "agent"

    tags: list[str] = []

    for s in spans:
        tags.extend(s.tags)

    tags = sorted(set(tags))[:32]

    return ExecutionAggregate(
        execution_id=execution_id,
        execution_type=exec_type,
        trace_id=trace_id,
        root_span_id=root_span_id,
        parent_execution_id=next(
            (s.parent_execution_id for s in spans if s.parent_execution_id), None
        ),
        parent_trace_id=next((s.parent_trace_id for s in spans if s.parent_trace_id), None),
        session_id=next((s.session_id for s in spans if s.session_id), None),
        user_session_id=next((s.user_session_id for s in spans if s.user_session_id), None),
        environment_id=next((s.environment_id for s in spans if s.environment_id), None),
        agent_id=next((s.agent_id for s in spans if s.agent_id), None),
        agent_version_id=next((s.agent_version_id for s in spans if s.agent_version_id), None),
        agent_name=next((s.agent_name for s in spans if s.agent_name), None),
        initiating_user_id=next(
            (s.initiating_user_id for s in spans if s.initiating_user_id),
            next((e.initiating_user_id for e in events if e.initiating_user_id), None),
        ),
        effective_actor_id=next(
            (s.effective_actor_id for s in spans if s.effective_actor_id),
            next((e.effective_actor_id for e in events if e.effective_actor_id), None),
        ),
        effective_actor_type=next(
            (s.effective_actor_type for s in spans if s.effective_actor_type), None
        ),
        invocation_source=next((s.invocation_source for s in spans if s.invocation_source), None),
        application_name=next((s.application_name for s in spans if s.application_name), None),
        client_name=next((s.client_name for s in spans if s.client_name), None),
        request_id=next((s.request_id for s in spans if s.request_id), None),
        replay_of_execution_id=next(
            (s.replay_of_execution_id for s in spans if s.replay_of_execution_id), None
        ),
        replay_reason=next((s.replay_reason for s in spans if s.replay_reason), None),
        repository_ref=next((s.repository_ref for s in spans if s.repository_ref), None),
        branch_ref=next((s.branch_ref for s in spans if s.branch_ref), None),
        commit_sha=next((s.commit_sha for s in spans if s.commit_sha), None),
        deployment_name=next((s.deployment_name for s in spans if s.deployment_name), None),
        region_name=next((s.region_name for s in spans if s.region_name), None),
        runtime_name=next((s.runtime_name for s in spans if s.runtime_name), None),
        framework=next((s.framework for s in spans if s.framework), None),
        framework_version=next((s.framework_version for s in spans if s.framework_version), None),
        status=status,
        start_time=_nano_to_dt(start_nano),
        end_time=_nano_to_dt(end_nano),
        duration_ms=duration_ms,
        span_count=len(spans),
        node_count=node_count,
        generation_count=generation_count,
        tool_count=tool_count,
        sdk_count=sdk_count,
        mcp_tool_count=mcp_tool_count,
        error_count=error_count,
        retry_count=retry_count,
        input_tokens=sum(s.input_tokens for s in spans),
        output_tokens=sum(s.output_tokens for s in spans),
        total_cost_micros=sum(s.cost_micros for s in spans),
        provider=next((s.provider for s in spans if s.provider), None),
        model=next((s.model for s in spans if s.model), None),
        sdk_name=next((s.sdk_name for s in spans if s.sdk_name), None),
        mcp_server=next((s.mcp_server for s in spans if s.mcp_server), None),
        sample_rate=min((s.sample_rate for s in spans), default=1.0),
        is_live=is_live,
        is_partial=is_partial,
        is_malformed=malformed,
        has_cycle=has_cycle,
        has_late_data=has_late_data,
        capture_level=capture_level,
        tags=tags,
    )


def execution_index_row(
    org_id: UUID,
    project_id: UUID,
    agg: ExecutionAggregate,
    *,
    version: int,
    nano_to_ch: Any,
) -> dict[str, Any]:

    start_nano = int(agg.start_time.timestamp() * 1_000_000_000) if agg.start_time else 0

    end_nano = int(agg.end_time.timestamp() * 1_000_000_000) if agg.end_time else 0

    return {
        "organization_id": str(org_id),
        "project_id": str(project_id),
        "execution_id": agg.execution_id,
        "execution_type": agg.execution_type,
        "trace_id": agg.trace_id,
        "root_span_id": agg.root_span_id or "",
        "parent_execution_id": agg.parent_execution_id or "",
        "parent_trace_id": agg.parent_trace_id or "",
        "session_id": agg.session_id or "",
        "user_session_id": agg.user_session_id or "",
        "environment_id": agg.environment_id or "",
        "agent_id": agg.agent_id or "",
        "agent_version_id": agg.agent_version_id or "",
        "initiating_user_id": agg.initiating_user_id or "",
        "invocation_source": agg.invocation_source or "",
        "application_name": agg.application_name or "",
        "client_name": agg.client_name or "",
        "request_id": agg.request_id or "",
        "replay_of_execution_id": agg.replay_of_execution_id or "",
        "framework": agg.framework or "",
        "status": agg.status,
        "start_time": nano_to_ch(start_nano),
        "end_time": nano_to_ch(end_nano),
        "duration_ms": agg.duration_ms or 0,
        "span_count": agg.span_count,
        "node_count": agg.node_count,
        "generation_count": agg.generation_count,
        "tool_count": agg.tool_count,
        "sdk_count": agg.sdk_count,
        "error_count": agg.error_count,
        "retry_count": agg.retry_count,
        "input_tokens": agg.input_tokens,
        "output_tokens": agg.output_tokens,
        "total_cost_micros": agg.total_cost_micros,
        "sample_rate": agg.sample_rate,
        "provider": agg.provider or "",
        "sdk_name": agg.sdk_name or "",
        "mcp_server": agg.mcp_server or "",
        "is_live": 1 if agg.is_live else 0,
        "is_partial": 1 if agg.is_partial else 0,
        "version": version,
    }


def projection_outbox_payload(agg: ExecutionAggregate) -> dict[str, Any]:

    return {
        "execution_id": agg.execution_id,
        "execution_type": agg.execution_type,
        "trace_id": agg.trace_id,
        "parent_execution_id": agg.parent_execution_id,
        "parent_trace_id": agg.parent_trace_id,
        "session_id": agg.session_id,
        "environment_id": agg.environment_id,
        "status": agg.status,
        "agent_id": agg.agent_id,
        "agent_version_id": agg.agent_version_id,
        "initiating_user_id": agg.initiating_user_id,
        "invocation_source": agg.invocation_source,
        "application_name": agg.application_name,
        "client_name": agg.client_name,
        "request_id": agg.request_id,
        "replay_of_execution_id": agg.replay_of_execution_id,
        "span_count": agg.span_count,
        "generation_count": agg.generation_count,
        "tool_count": agg.tool_count,
        "sdk_count": agg.sdk_count,
        "error_count": agg.error_count,
        "total_cost_micros": agg.total_cost_micros,
        "duration_ms": agg.duration_ms,
        "is_partial": agg.is_partial,
        "started_at": agg.start_time.isoformat() if agg.start_time else None,
        "ended_at": agg.end_time.isoformat() if agg.end_time else None,
        "model": agg.model,
        "retry_count": agg.retry_count,
        "tokens_in": agg.input_tokens,
        "tokens_out": agg.output_tokens,
    }


def is_terminal_execution(agg: ExecutionAggregate) -> bool:

    return agg.status in TERMINAL_STATUSES and not agg.is_live
