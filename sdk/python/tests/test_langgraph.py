from __future__ import annotations

from typing import TypedDict

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from aap_trace.integrations.langgraph import describe_langgraph, instrument_langgraph


class LoopState(TypedDict):
    attempts: int
    result: str


def _loop_graph() -> object:
    builder = StateGraph(LoopState)

    def analyze(state: LoopState) -> dict[str, int]:
        return {"attempts": state["attempts"] + 1}

    def route(state: LoopState) -> str:
        return "retry" if state["attempts"] < 2 else "coding"

    def retry(state: LoopState) -> dict[str, str]:
        return {"result": f"retry-{state['attempts']}"}

    def coding(state: LoopState) -> dict[str, str]:
        return {"result": "patched"}

    builder.add_node("analysis", analyze)
    builder.add_node("retry", retry)
    builder.add_node("coding", coding)
    builder.add_edge(START, "analysis")
    builder.add_conditional_edges("analysis", route, {"retry": "retry", "coding": "coding"})
    builder.add_edge("retry", "analysis")
    builder.add_edge("coding", END)
    return builder.compile(checkpointer=InMemorySaver())


def test_instrumented_graph_captures_nodes_branches_loops_and_checkpoints(
    configured_client: object,
    memory_exporter: InMemorySpanExporter,
) -> None:
    graph = instrument_langgraph(
        _loop_graph(),
        graph_name="foss-remediation",
        graph_version="git:abc123",
    )

    result = graph.invoke(
        {"attempts": 0, "result": ""},
        {"configurable": {"thread_id": "session-1"}},
    )

    assert result == {"attempts": 2, "result": "patched"}
    spans = memory_exporter.get_finished_spans()
    agent = next(span for span in spans if span.attributes["aap.observation.type"] == "agent")
    nodes = [span for span in spans if span.attributes["aap.observation.type"] == "node"]
    assert agent.attributes["aap.graph.name"] == "foss-remediation"
    assert {span.name for span in nodes} >= {"analysis", "retry", "coding"}
    analysis_iterations = sorted(
        int(span.attributes["aap.graph.iteration"]) for span in nodes if span.name == "analysis"
    )
    assert analysis_iterations == [1, 2]
    assert all(
        span.attributes["aap.execution.id"] == agent.attributes["aap.execution.id"]
        for span in nodes
    )
    event_names = {event.name for span in nodes for event in span.events}
    assert "state.transition" in event_names
    assert "checkpoint.saved" in event_names
    assert "node.retry" in event_names

    architecture = describe_langgraph(graph)
    assert {node["name"] for node in architecture["nodes"]} >= {"analysis", "retry", "coding"}
    assert any(edge["conditional"] for edge in architecture["edges"])


class ApprovalState(TypedDict):
    approved: bool


def _approval_graph() -> object:
    builder = StateGraph(ApprovalState)

    def approve(_: ApprovalState) -> dict[str, bool]:
        return {"approved": bool(interrupt("Approve remediation patch?"))}

    builder.add_node("human_approval", approve)
    builder.add_edge(START, "human_approval")
    builder.add_edge("human_approval", END)
    return builder.compile(checkpointer=InMemorySaver())


def test_interrupt_and_resume_are_observable(
    configured_client: object,
    memory_exporter: InMemorySpanExporter,
) -> None:
    graph = instrument_langgraph(_approval_graph(), graph_name="approval")
    config = {"configurable": {"thread_id": "approval-1"}}

    interrupted = graph.invoke({"approved": False}, config)
    assert "__interrupt__" in interrupted
    resumed = graph.invoke(Command(resume=True), config)
    assert resumed["approved"] is True

    events = [event for span in memory_exporter.get_finished_spans() for event in span.events]
    assert any(event.name == "execution.interrupted" for event in events)
    assert any(event.name == "execution.resumed" for event in events)


@pytest.mark.asyncio
async def test_async_graph_preserves_node_parentage(
    configured_client: object,
    memory_exporter: InMemorySpanExporter,
) -> None:
    builder = StateGraph(LoopState)

    async def node(state: LoopState) -> dict[str, str]:
        return {"result": f"async-{state['attempts']}"}

    builder.add_node("async_node", node)
    builder.add_edge(START, "async_node")
    builder.add_edge("async_node", END)
    graph = instrument_langgraph(builder.compile(), graph_name="async-graph")

    result = await graph.ainvoke({"attempts": 1, "result": ""})

    assert result["result"] == "async-1"
    spans = memory_exporter.get_finished_spans()
    agent = next(span for span in spans if span.attributes["aap.observation.type"] == "agent")
    node_span = next(span for span in spans if span.name == "async_node")
    assert node_span.parent.span_id == agent.context.span_id
