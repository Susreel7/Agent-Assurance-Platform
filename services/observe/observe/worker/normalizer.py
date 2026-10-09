"""Map OTLP spans/logs to normalized Observe kinds and observation types."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from observe.ingest.otlp import RawLogRecord, RawSpan

MAPPING_REVISION = 2

NORMALIZED_KINDS = frozenset(
    {
        "workflow",
        "agent",
        "plan",
        "inference",
        "tool",
        "mcp_tool",
        "retrieval",
        "embedding",
        "memory",
        "guardrail",
        "handoff",
        "http",
        "unknown",
    }
)

OBSERVATION_TYPES = frozenset(
    {
        "agent",
        "node",
        "generation",
        "tool",
        "sdk",
        "retrieval",
        "chain",
        "http",
        "database",
        "state_transition",
        "event",
        "evaluation",
        "error",
        "retry",
        "mcp",
        "a2a",
        "checkpoint",
        "human_approval",
        "guardrail",
        "memory",
        "embedding",
        "unknown",
    }
)


@dataclass(frozen=True, slots=True)
class NormalizedSpan:
    trace_id: str
    span_id: str
    parent_span_id: str | None
    execution_id: str | None
    parent_execution_id: str | None
    execution_type: str | None
    session_id: str | None
    user_session_id: str | None
    environment_id: str | None
    service_name: str | None
    agent_id: str | None
    agent_name: str | None
    agent_version_id: str | None
    kind: str
    observation_type: str
    operation_name: str
    source_convention: str
    mapping_revision: int
    status_code: str
    outcome: str
    model: str | None
    tool_name: str | None
    provider: str | None
    sdk_name: str | None
    sdk_version: str | None
    sdk_operation: str | None
    mcp_server: str | None
    mcp_method: str | None
    retry_attempt: int
    graph_node_id: str | None
    graph_node_path: str | None
    initiating_user_id: str | None
    effective_actor_id: str | None
    effective_actor_type: str | None
    start_time_unix_nano: int
    end_time_unix_nano: int
    duration_ms: float
    input_tokens: int
    output_tokens: int
    cost_micros: int
    clock_skew_flag: bool
    is_terminal: bool
    tags: list[str]
    search_text: str
    content_fingerprint: str
    payload_fields: dict[str, Any]
    payload_preprocessed: bool = False
    invocation_source: str | None = None
    application_name: str | None = None
    client_name: str | None = None
    request_id: str | None = None
    replay_of_execution_id: str | None = None
    replay_reason: str | None = None
    repository_ref: str | None = None
    branch_ref: str | None = None
    commit_sha: str | None = None
    deployment_name: str | None = None
    region_name: str | None = None
    runtime_name: str | None = None
    framework: str | None = None
    framework_version: str | None = None
    parent_trace_id: str | None = None
    sample_rate: float = 1.0
    mcp_role: str | None = None
    mcp_request_id: str | None = None
    a2a_target_agent_id: str | None = None
    a2a_target_execution_id: str | None = None
    a2a_target_trace_id: str | None = None


@dataclass(frozen=True, slots=True)
class NormalizedLogEvent:
    trace_id: str
    span_id: str | None
    log_record_uid: str
    execution_id: str | None
    event_type: str
    observation_type: str
    event_time_unix_nano: int
    status: str
    initiating_user_id: str | None
    effective_actor_id: str | None
    agent_id: str | None
    model: str | None
    tool_name: str | None
    sdk_name: str | None
    sdk_operation: str | None
    mcp_server: str | None
    mcp_method: str | None
    sequence: int
    attributes: dict[str, str]
    content_fingerprint: str


def _fingerprint_span(span: RawSpan) -> str:
    payload = {
        "trace_id": span.trace_id,
        "span_id": span.span_id,
        "name": span.name,
        "start": span.start_time_unix_nano,
        "end": span.end_time_unix_nano,
        "attrs": span.attributes,
    }
    raw = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _fingerprint_log(record: RawLogRecord) -> str:
    payload = {
        "trace_id": record.trace_id,
        "span_id": record.span_id,
        "time": record.time_unix_nano,
        "attrs": record.attributes,
    }
    raw = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _attr(span: RawSpan, key: str) -> Any:
    if key in span.attributes:
        return span.attributes[key]
    return span.resource_attributes.get(key)


def _bounded_str(value: Any, max_len: int = 256) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text[:max_len] if text else None


def _user_id(span: RawSpan) -> str | None:
    explicit = _attr(span, "aap.user.id")
    if explicit is not None:
        return _bounded_str(explicit, 256)
    enduser = _attr(span, "enduser.id")
    if enduser is not None:
        return _bounded_str(enduser, 256)
    return None


def _detect_convention(span: RawSpan) -> str:
    attrs = {**span.resource_attributes, **span.attributes}
    if any(k.startswith("gen_ai.") for k in attrs):
        return "otel_genai_1.37"
    if any(k.startswith("llm.") or k.startswith("openinference.") for k in attrs):
        return "openinference"
    if any(k.startswith("traceloop.") for k in attrs):
        return "openllmetry"
    if "langgraph.node" in attrs or "langgraph.step" in attrs:
        return "langgraph"
    if "openai.agents." in "".join(attrs.keys()):
        return "openai_agents"
    if any(k.startswith("gcp.adk.") or k.startswith("adk.") for k in attrs):
        return "google_adk"
    sdk_name = str(attrs.get("telemetry.sdk.name", ""))
    if any(k.startswith("sk.") for k in attrs) or "semantic_kernel" in sdk_name:
        return "semantic_kernel"
    if any(k.startswith("crewai.") for k in attrs):
        return "crewai"
    if any(k.startswith("autogen.") for k in attrs):
        return "autogen"
    if any(k.startswith("mcp.") for k in attrs):
        return "mcp"
    for ev in span.events:
        if ev.get("name", "").startswith("gen_ai."):
            return "legacy_genai_events"
    return "unknown"


def _explicit_observation_type(span: RawSpan) -> str | None:
    raw = _attr(span, "aap.observation.type")
    if isinstance(raw, str) and raw in OBSERVATION_TYPES:
        return raw
    return None


def _map_kind(span: RawSpan, convention: str) -> str:
    op = _attr(span, "gen_ai.operation.name")
    if isinstance(op, str):
        mapping = {
            "chat": "inference",
            "generate_content": "inference",
            "embeddings": "embedding",
            "execute_tool": "tool",
            "invoke_agent": "agent",
            "create_agent": "agent",
            "retrieval": "retrieval",
        }
        if op in mapping:
            return mapping[op]
        if op:
            return "unknown"

    tool_type = _attr(span, "gen_ai.tool.type")
    if tool_type == "mcp" or _attr(span, "mcp.tool.name"):
        return "mcp_tool"
    if _attr(span, "gen_ai.tool.name") or _attr(span, "tool.name"):
        return "tool"
    if _attr(span, "gen_ai.retrieval.query") or span.name.lower().find("retriev") >= 0:
        return "retrieval"
    if span.name.lower().find("embed") >= 0:
        return "embedding"
    if span.name.lower().find("guard") >= 0:
        return "guardrail"
    if span.name.lower().find("handoff") >= 0:
        return "handoff"
    if span.name.lower().find("workflow") >= 0 or convention == "langgraph":
        return "workflow"
    if span.name.lower().find("plan") >= 0:
        return "plan"
    if span.name.lower().startswith("http") or _attr(span, "http.route"):
        return "http"
    if _attr(span, "gen_ai.agent.name") or _attr(span, "gen_ai.agent.id"):
        return "agent"
    return "unknown"


def _map_observation_type(span: RawSpan, convention: str, kind: str) -> str:
    explicit = _explicit_observation_type(span)
    if explicit:
        return explicit
    if _attr(span, "langgraph.node") or _attr(span, "aap.graph.node.id"):
        return "node"
    if kind == "inference":
        return "generation"
    if kind == "mcp_tool":
        return "mcp"
    if kind == "embedding":
        return "embedding"
    if kind == "retrieval":
        return "retrieval"
    if kind == "guardrail":
        return "guardrail"
    if kind == "memory" or "memory" in span.name.lower():
        return "memory"
    if kind == "http":
        return "http"
    if kind == "tool":
        return "tool"
    if kind == "agent":
        return "agent"
    if _attr(span, "aap.sdk.name") or _attr(span, "aap.sdk.operation"):
        return "sdk"
    if convention == "langgraph" and kind == "workflow":
        return "node"
    return "unknown"


def _outcome(span: RawSpan) -> str:
    if span.status_code == "error":
        return "error"
    finish = _attr(span, "gen_ai.response.finish_reasons")
    if isinstance(finish, list) and finish:
        if any(str(x).lower() in {"length", "content_filter"} for x in finish):
            return "partial"
    if span.end_time_unix_nano > span.start_time_unix_nano:
        return "success"
    return "open"


def _collect_payload_fields(span: RawSpan) -> dict[str, Any]:
    payload_fields: dict[str, Any] = {}
    for key in (
        "gen_ai.input.messages",
        "gen_ai.output.messages",
        "gen_ai.system_instructions",
        "gen_ai.tool.call.arguments",
        "gen_ai.tool.call.result",
    ):
        if key in span.attributes:
            val = span.attributes[key]
            if isinstance(val, str) and val.startswith("ref:"):
                payload_fields[key] = val
                continue
            if key.endswith(".digest") or key.endswith(".size"):
                continue
            payload_fields[key] = val
    return payload_fields


def normalize_span(span: RawSpan, *, payload_preprocessed: bool = False) -> NormalizedSpan:
    convention = _detect_convention(span)
    kind = _map_kind(span, convention)
    if kind not in NORMALIZED_KINDS:
        kind = "unknown"
    observation_type = _map_observation_type(span, convention, kind)
    if observation_type not in OBSERVATION_TYPES:
        observation_type = "unknown"

    session_id = _bounded_str(
        _attr(span, "gen_ai.conversation.id") or _attr(span, "aap.session.id")
    )
    user_session = _bounded_str(_attr(span, "aap.user.session_id"))
    execution_id = _bounded_str(_attr(span, "aap.execution.id"))
    parent_execution_id = _bounded_str(_attr(span, "aap.execution.parent_id"))
    execution_type = _bounded_str(_attr(span, "aap.execution.type"), 64)
    environment_id = _bounded_str(_attr(span, "aap.environment.id"))
    service = _attr(span, "service.name") or span.resource_attributes.get("service.name")
    agent_id = _bounded_str(_attr(span, "gen_ai.agent.id") or _attr(span, "aap.agent.id"))
    agent_name = _bounded_str(_attr(span, "gen_ai.agent.name"))
    agent_version_id = _bounded_str(_attr(span, "aap.agent.version_id"))
    model = _bounded_str(
        _attr(span, "gen_ai.response.model") or _attr(span, "gen_ai.request.model")
    )
    tool_name = _bounded_str(_attr(span, "gen_ai.tool.name") or _attr(span, "mcp.tool.name"))
    provider = _bounded_str(_attr(span, "gen_ai.provider.name"))
    sdk_name = _bounded_str(_attr(span, "aap.sdk.name"))
    sdk_version = _bounded_str(_attr(span, "aap.sdk.version"), 64)
    sdk_operation = _bounded_str(_attr(span, "aap.sdk.operation"), 256)
    mcp_server = _bounded_str(_attr(span, "aap.mcp.server") or _attr(span, "mcp.server.name"))
    mcp_method = _bounded_str(_attr(span, "aap.mcp.method") or _attr(span, "mcp.method"), 128)
    mcp_role = _bounded_str(_attr(span, "aap.mcp.role"), 16)
    mcp_request_id = _bounded_str(_attr(span, "aap.mcp.request_id"), 128)
    a2a_target_agent_id = _bounded_str(_attr(span, "aap.a2a.target_agent_id"), 128)
    a2a_target_execution_id = _bounded_str(_attr(span, "aap.a2a.target_execution_id"), 128)
    a2a_target_trace_id = _bounded_str(_attr(span, "aap.a2a.target_trace_id"), 64)
    retry_attempt = int(_attr(span, "aap.retry.attempt") or 0)
    graph_node_id = _bounded_str(_attr(span, "aap.graph.node.id") or _attr(span, "langgraph.node"))
    graph_node_path = _bounded_str(_attr(span, "aap.graph.node.path"), 512)
    initiating_user_id = _user_id(span)
    effective_actor_id = _bounded_str(_attr(span, "aap.actor.id") or initiating_user_id)
    effective_actor_type = _bounded_str(_attr(span, "aap.actor.type"), 32)
    invocation_source = _bounded_str(_attr(span, "aap.invocation.source"), 64)
    application_name = _bounded_str(_attr(span, "aap.invocation.application"))
    client_name = _bounded_str(_attr(span, "aap.invocation.client"))
    request_id = _bounded_str(_attr(span, "aap.request.id"))
    replay_of_execution_id = _bounded_str(_attr(span, "aap.replay.of_execution_id"), 128)
    replay_reason = _bounded_str(_attr(span, "aap.replay.reason"), 512)
    repository_ref = _bounded_str(
        _attr(span, "vcs.repository.url.full") or _attr(span, "aap.repository"), 512
    )
    branch_ref = _bounded_str(
        _attr(span, "vcs.ref.head.name") or _attr(span, "aap.repository.branch"), 256
    )
    commit_sha = _bounded_str(
        _attr(span, "vcs.ref.head.revision") or _attr(span, "aap.repository.commit"), 128
    )
    deployment_name = _bounded_str(_attr(span, "service.instance.id"), 256)
    region_name = _bounded_str(
        _attr(span, "cloud.region") or _attr(span, "aap.deployment.region"), 128
    )
    runtime_name = _bounded_str(
        _attr(span, "process.runtime.name") or _attr(span, "aap.runtime.name"), 128
    )
    framework = _bounded_str(_attr(span, "aap.framework.name"), 128) or convention
    framework_version = _bounded_str(_attr(span, "aap.framework.version"), 64)
    parent_trace_id = _bounded_str(
        _attr(span, "aap.trace.parent_id") or _attr(span, "aap.parent_trace_id"), 64
    )

    duration_ms = max(0.0, (span.end_time_unix_nano - span.start_time_unix_nano) / 1_000_000)
    in_tok = int(_attr(span, "gen_ai.usage.input_tokens") or 0)
    out_tok = int(_attr(span, "gen_ai.usage.output_tokens") or 0)
    cost = int(_attr(span, "gen_ai.usage.cost") or 0)

    is_terminal = span.end_time_unix_nano > 0 and _outcome(span) != "open"
    tags: list[str] = []
    if provider:
        tags.append(f"provider:{provider}")
    if model:
        tags.append(f"model:{model}")
    if observation_type:
        tags.append(f"observation:{observation_type}")

    search_bits = [span.name, kind, observation_type, str(model or ""), str(tool_name or "")]
    search_text = " ".join(x for x in search_bits if x)[:2048]

    payload_fields = _collect_payload_fields(span)
    try:
        sample_rate = float(_attr(span, "aap.sampling.rate") or 1)
    except (TypeError, ValueError):
        sample_rate = 1.0
    sample_rate = min(1.0, max(0.0, sample_rate))

    return NormalizedSpan(
        trace_id=span.trace_id,
        span_id=span.span_id,
        parent_span_id=span.parent_span_id,
        execution_id=execution_id,
        parent_execution_id=parent_execution_id,
        execution_type=execution_type,
        session_id=session_id,
        user_session_id=user_session,
        environment_id=environment_id,
        service_name=_bounded_str(service),
        agent_id=agent_id,
        agent_name=agent_name,
        agent_version_id=agent_version_id,
        kind=kind,
        observation_type=observation_type,
        operation_name=span.name[:512],
        source_convention=convention,
        mapping_revision=MAPPING_REVISION,
        status_code=span.status_code,
        outcome=_outcome(span),
        model=model,
        tool_name=tool_name,
        provider=provider,
        sdk_name=sdk_name,
        sdk_version=sdk_version,
        sdk_operation=sdk_operation,
        mcp_server=mcp_server,
        mcp_method=mcp_method,
        retry_attempt=retry_attempt,
        graph_node_id=graph_node_id,
        graph_node_path=graph_node_path,
        initiating_user_id=initiating_user_id,
        effective_actor_id=effective_actor_id,
        effective_actor_type=effective_actor_type,
        start_time_unix_nano=span.start_time_unix_nano,
        end_time_unix_nano=span.end_time_unix_nano,
        duration_ms=duration_ms,
        input_tokens=in_tok,
        output_tokens=out_tok,
        cost_micros=cost,
        clock_skew_flag=span.end_time_unix_nano < span.start_time_unix_nano,
        is_terminal=is_terminal,
        tags=tags,
        search_text=search_text,
        content_fingerprint=_fingerprint_span(span),
        payload_fields=payload_fields,
        payload_preprocessed=payload_preprocessed,
        invocation_source=invocation_source,
        application_name=application_name,
        client_name=client_name,
        request_id=request_id,
        replay_of_execution_id=replay_of_execution_id,
        replay_reason=replay_reason,
        repository_ref=repository_ref,
        branch_ref=branch_ref,
        commit_sha=commit_sha,
        deployment_name=deployment_name,
        region_name=region_name,
        runtime_name=runtime_name,
        framework=framework,
        framework_version=framework_version,
        parent_trace_id=parent_trace_id,
        sample_rate=sample_rate,
        mcp_role=mcp_role,
        mcp_request_id=mcp_request_id,
        a2a_target_agent_id=a2a_target_agent_id,
        a2a_target_execution_id=a2a_target_execution_id,
        a2a_target_trace_id=a2a_target_trace_id,
    )


def normalize_log_record(record: RawLogRecord) -> NormalizedLogEvent:
    attrs = {**record.resource_attributes, **record.attributes}
    event_type = str(attrs.get("aap.event.type") or record.event_name or "event.unknown")[:128]
    observation_type = str(attrs.get("aap.observation.type") or "event")
    if observation_type not in OBSERVATION_TYPES:
        observation_type = "event"
    execution_id = _bounded_str(attrs.get("aap.execution.id"))
    initiating_user_id = _bounded_str(attrs.get("aap.user.id") or attrs.get("enduser.id"))
    effective_actor_id = _bounded_str(attrs.get("aap.actor.id") or initiating_user_id)
    status = str(attrs.get("aap.event.status") or "info")[:32]
    sequence = int(attrs.get("aap.observation.sequence") or 0)
    bounded_attrs = {
        k[:128]: str(v)[:512]
        for k, v in attrs.items()
        if k.startswith("aap.") and k not in {"aap.payload.input", "aap.payload.output"}
    }
    return NormalizedLogEvent(
        trace_id=record.trace_id,
        span_id=record.span_id,
        log_record_uid=record.log_record_uid,
        execution_id=execution_id,
        event_type=event_type,
        observation_type=observation_type,
        event_time_unix_nano=record.time_unix_nano,
        status=status,
        initiating_user_id=initiating_user_id,
        effective_actor_id=effective_actor_id,
        agent_id=_bounded_str(attrs.get("gen_ai.agent.id") or attrs.get("aap.agent.id")),
        model=_bounded_str(attrs.get("gen_ai.request.model")),
        tool_name=_bounded_str(attrs.get("gen_ai.tool.name")),
        sdk_name=_bounded_str(attrs.get("aap.sdk.name")),
        sdk_operation=_bounded_str(attrs.get("aap.sdk.operation"), 256),
        mcp_server=_bounded_str(attrs.get("aap.mcp.server")),
        mcp_method=_bounded_str(attrs.get("aap.mcp.method"), 128),
        sequence=sequence,
        attributes=bounded_attrs,
        content_fingerprint=_fingerprint_log(record),
    )


def _map_span_event_observation(name: str) -> str:
    lowered = name.lower()
    if "error" in lowered or "exception" in lowered:
        return "error"
    if "checkpoint" in lowered:
        return "checkpoint"
    if "retry" in lowered:
        return "retry"
    return "event"


def normalize_span_otlp_event(span: RawSpan, event: dict[str, Any]) -> NormalizedLogEvent:
    name = str(event.get("name") or "span.event")[:128]
    time_nano = int(event.get("timeUnixNano") or event.get("time_unix_nano") or 0)
    event_attrs: dict[str, Any] = {}
    raw_event_attrs = event.get("attributes", {})
    if isinstance(raw_event_attrs, dict):
        event_attrs.update(raw_event_attrs)
    else:
        for item in raw_event_attrs:
            if isinstance(item, dict) and item.get("key"):
                key = str(item["key"])
                if key.startswith("gen_ai.input") or key.startswith("gen_ai.output"):
                    continue
                val = item.get("value", {})
                if isinstance(val, dict) and "stringValue" in val:
                    event_attrs[key] = str(val["stringValue"])[:512]
    merged = {**span.resource_attributes, **span.attributes, **event_attrs}
    observation_type = _map_span_event_observation(name)
    if merged.get("aap.observation.type") in OBSERVATION_TYPES:
        observation_type = str(merged["aap.observation.type"])
    initiating_user_id = _bounded_str(merged.get("aap.user.id") or merged.get("enduser.id"))
    bounded_attrs = {
        k[:128]: str(v)[:512]
        for k, v in merged.items()
        if k.startswith("aap.") and not k.startswith("aap.payload.")
    }
    uid = f"{span.trace_id}:{span.span_id}:{name}:{time_nano}"
    return NormalizedLogEvent(
        trace_id=span.trace_id,
        span_id=span.span_id,
        log_record_uid=uid,
        execution_id=_bounded_str(merged.get("aap.execution.id")),
        event_type=str(merged.get("aap.event.type") or name)[:128],
        observation_type=observation_type,
        event_time_unix_nano=time_nano,
        status=str(merged.get("aap.event.status") or "info")[:32],
        initiating_user_id=initiating_user_id,
        effective_actor_id=_bounded_str(merged.get("aap.actor.id") or initiating_user_id),
        agent_id=_bounded_str(merged.get("gen_ai.agent.id") or merged.get("aap.agent.id")),
        model=_bounded_str(merged.get("gen_ai.request.model")),
        tool_name=_bounded_str(merged.get("gen_ai.tool.name")),
        sdk_name=_bounded_str(merged.get("aap.sdk.name")),
        sdk_operation=_bounded_str(merged.get("aap.sdk.operation"), 256),
        mcp_server=_bounded_str(merged.get("aap.mcp.server")),
        mcp_method=_bounded_str(merged.get("aap.mcp.method"), 128),
        sequence=int(merged.get("aap.observation.sequence") or 0),
        attributes=bounded_attrs,
        content_fingerprint="sha256:" + hashlib.sha256(uid.encode()).hexdigest(),
    )


def detect_graph_flags(spans: list[NormalizedSpan]) -> tuple[bool, bool, str | None]:
    """malformed, has_cycle, root_span_id."""
    if not spans:
        return False, False, None
    ids = {s.span_id for s in spans}
    parent_map = {s.span_id: s.parent_span_id for s in spans}
    roots = [s.span_id for s in spans if not s.parent_span_id or s.parent_span_id not in ids]
    malformed = len(roots) != 1
    root = roots[0] if len(roots) == 1 else None

    has_cycle = False
    for start in ids:
        seen: set[str] = set()
        cur: str | None = start
        while cur is not None:
            if cur in seen:
                has_cycle = True
                break
            seen.add(cur)
            cur = parent_map.get(cur)
        if has_cycle:
            break

    return malformed, has_cycle, root


def execution_id_for_trace(spans: list[NormalizedSpan], trace_id: str) -> str:
    for span in spans:
        if span.execution_id:
            return span.execution_id
    for span in spans:
        if span.observation_type == "agent" and span.agent_id:
            return f"exec:{trace_id[:16]}:{span.span_id[:8]}"
    return f"exec:{trace_id}"
