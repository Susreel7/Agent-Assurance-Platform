"""Resolve pinned Prompt artifact revisions for an experiment spec."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from evaluate.clients.prompt import PromptClient
from evaluate.config import Settings
from evaluate.errors import UpstreamError, ValidationError


@dataclass(frozen=True, slots=True)
class ResolvedArtifact:
    artifact_key: str
    kind: str
    revision_id: UUID
    content_digest: str
    content: dict[str, Any]


@dataclass(slots=True)
class ResolvedExperimentPrompts:
    artifacts: list[ResolvedArtifact] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)
    digests: dict[str, str] = field(default_factory=dict)


def _pin_maps(spec: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []
    for key in (
        "prompt_revision_pins",
        "rule_revision_pins",
        "skill_revision_pins",
        "context_revision_pins",
    ):
        pins = spec.get(key)
        if isinstance(pins, dict) and pins:
            out.append((key.removesuffix("_revision_pins"), pins))
    return out


async def resolve_pinned_prompts(
    settings: Settings,
    prompt: PromptClient,
    *,
    org_id: UUID,
    project_id: UUID,
    spec: dict[str, Any],
) -> ResolvedExperimentPrompts:
    resolved = ResolvedExperimentPrompts()
    for _kind_label, pin_map in _pin_maps(spec):
        for artifact_key, revision_id_raw in pin_map.items():
            revision_id = UUID(str(revision_id_raw))
            internal = await prompt.fetch_revision_internal(
                org_id=org_id,
                project_id=project_id,
                artifact_key=str(artifact_key),
                revision_id=revision_id,
            )
            runtime = await prompt.fetch_runtime_artifact(
                org_id=org_id,
                project_id=project_id,
                artifact_key=str(artifact_key),
                revision_id=revision_id,
            )
            internal_rev = internal.get("revision_id") or internal.get("id")
            if str(internal_rev) != str(revision_id):
                raise ValidationError("internal prompt revision mismatch")
            if str(runtime.get("revision_id")) != str(revision_id):
                raise ValidationError("runtime prompt revision mismatch")
            if runtime.get("content_digest") != internal.get("content_digest"):
                raise ValidationError("prompt runtime/internal digest mismatch")
            content = runtime.get("content")
            if not isinstance(content, dict):
                raise UpstreamError("prompt runtime content missing")
            kind = str(runtime.get("kind") or internal.get("kind") or "prompt")
            item = ResolvedArtifact(
                artifact_key=str(artifact_key),
                kind=kind,
                revision_id=revision_id,
                content_digest=str(runtime["content_digest"]),
                content=content,
            )
            resolved.artifacts.append(item)
            resolved.digests[f"{kind}:{artifact_key}"] = item.content_digest
            if kind == "prompt":
                msgs = content.get("messages")
                if isinstance(msgs, list):
                    for m in msgs:
                        if isinstance(m, dict):
                            resolved.messages.append(m)
    if not resolved.messages and spec.get("fallback_user_message") is not False:
        resolved.messages.append({"role": "user", "content": "{{input}}"})
    return resolved


def apply_example_to_messages(
    messages: list[dict[str, Any]], example_input: dict[str, Any]
) -> list[dict[str, Any]]:
    rendered: list[dict[str, Any]] = []
    input_blob = example_input if isinstance(example_input, dict) else {"input": example_input}
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if isinstance(content, str):
            out = content
            for k, v in input_blob.items():
                out = out.replace(f"{{{{{k}}}}}", str(v))
            if "{{input}}" in out and "input" in input_blob:
                out = out.replace("{{input}}", str(input_blob.get("input", input_blob)))
            rendered.append({**msg, "content": out})
        else:
            rendered.append(dict(msg))
    if not rendered:
        rendered.append({"role": "user", "content": str(input_blob)})
    return rendered
