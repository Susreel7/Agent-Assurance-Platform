"""GenAI semantic convention attribute builders (OTel GenAI 1.37+)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from aap_trace.capture import CaptureMode, apply_capture


def base_resource_attrs(
    *,
    organization_id: str,
    project_id: str,
    service_name: str,
    environment: str,
    agent_id: str | None,
    agent_name: str | None,
    agent_version: str | None,
    metadata: Mapping[str, str],
) -> dict[str, str]:
    attrs: dict[str, str] = {
        "service.name": service_name,
        "deployment.environment": environment,
        "aap.organization.id": organization_id,
        "aap.project.id": project_id,
        "aap.environment.id": environment,
        # Compatibility aliases retained for 0.1.x collectors.
        "aap.organization_id": organization_id,
        "aap.project_id": project_id,
    }
    if agent_id:
        attrs["gen_ai.agent.id"] = agent_id
    if agent_name:
        attrs["gen_ai.agent.name"] = agent_name
    if agent_version:
        attrs["gen_ai.agent.version"] = agent_version
        attrs["aap.agent.version_id"] = agent_version
    for key, value in metadata.items():
        attrs[f"aap.metadata.{key}"] = value
    return attrs


def session_attrs(session_id: str | None, user_id: str | None) -> dict[str, str]:
    out: dict[str, str] = {}
    if session_id:
        out["gen_ai.conversation.id"] = session_id
        out["aap.user.session_id"] = session_id
    if user_id:
        out["enduser.id"] = user_id
        out["aap.user.id"] = user_id
    return out


def tag_attrs(tags: tuple[str, ...]) -> dict[str, str]:
    if not tags:
        return {}
    return {"aap.tags": ",".join(tags)}


def generation_attrs(
    *,
    provider: str,
    model: str,
    operation: str = "chat",
    capture_mode: CaptureMode,
    system_instructions: Any | None = None,
    input_messages: Any | None = None,
    output_messages: Any | None = None,
) -> dict[str, Any]:
    attrs: dict[str, Any] = {
        "gen_ai.operation.name": operation,
        "gen_ai.provider.name": provider,
        "gen_ai.request.model": model,
    }
    for field, value in (
        ("gen_ai.system_instructions", system_instructions),
        ("gen_ai.input.messages", input_messages),
        ("gen_ai.output.messages", output_messages),
    ):
        captured = apply_capture(capture_mode, field, value)
        if captured:
            attrs.update(captured)
    return attrs


def tool_attrs(
    *,
    name: str,
    tool_type: str = "function",
    arguments: Any | None = None,
    result: Any | None = None,
    capture_mode: CaptureMode,
) -> dict[str, Any]:
    attrs: dict[str, Any] = {
        "gen_ai.operation.name": "execute_tool",
        "gen_ai.tool.name": name,
        "gen_ai.tool.type": tool_type,
    }
    for field, value in (
        ("gen_ai.tool.call.arguments", arguments),
        ("gen_ai.tool.call.result", result),
    ):
        captured = apply_capture(capture_mode, field, value)
        if captured:
            attrs.update(captured)
    return attrs


def retrieval_attrs(
    *,
    query: str | None,
    capture_mode: CaptureMode,
) -> dict[str, Any]:
    attrs: dict[str, Any] = {"gen_ai.operation.name": "retrieval"}
    captured = apply_capture(capture_mode, "gen_ai.retrieval.query", query)
    if captured:
        attrs.update(captured)
    elif query is not None and capture_mode == CaptureMode.NONE:
        attrs["gen_ai.retrieval.query.length"] = str(len(query))
    return attrs
