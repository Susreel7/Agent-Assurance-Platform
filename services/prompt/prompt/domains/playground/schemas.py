"""Playground run request/response models."""

from __future__ import annotations

from typing import Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

PlaygroundMode = Literal["sync", "stream", "compare", "replay"]


class ArtifactRef(BaseModel):
    artifact_key: str | None = Field(
        default=None,
        description="Artifact key; required with label when revision_id is omitted.",
    )
    revision_id: UUID | None = Field(
        default=None,
        description="Pin a specific revision (ignores label on the same ref).",
    )
    label: str | None = Field(
        default=None,
        description="Label name (e.g. production); normalized to lowercase.",
    )


class PlaygroundRunRequest(BaseModel):
    mode: PlaygroundMode = Field(
        default="sync",
        description=(
            "Execution mode. `compare` runs parallel router calls (see compare output schema). "
            "`stream` must be used with sync mode only (`stream=true` on the request body)."
        ),
    )
    artifacts: list[ArtifactRef] = Field(
        min_length=1,
        description=(
            "Artifacts to resolve. For `compare`, provide at least two refs; messages are "
            "built by concatenating each artifact's `messages` (unless messages_override is set), "
            "then the same router request is executed once per resolved revision in parallel."
        ),
    )
    variables: dict[str, Any] = Field(default_factory=dict)
    model_alias: str = Field(min_length=1)
    model_settings: dict[str, Any] = Field(default_factory=dict)
    messages_override: list[dict[str, Any]] | None = Field(
        default=None,
        description="When set, replaces merged artifact messages before variable substitution.",
    )
    replay_run_id: UUID | None = Field(
        default=None,
        description="Source run for mode=replay (handled by replay endpoint).",
    )
    stream: bool = Field(
        default=False,
        description="When true with mode=sync, returns SSE from POST /playground/runs.",
    )

    @model_validator(mode="after")
    def _validate_mode_contract(self) -> Self:
        if self.stream and self.mode != "sync":
            raise ValueError("stream=true requires mode=sync")
        if self.mode == "compare":
            if len(self.artifacts) < 2:
                raise ValueError("compare mode requires at least two artifact refs")
        if self.mode == "replay" and self.replay_run_id is None:
            raise ValueError("replay mode requires replay_run_id")
        return self


class CompareVariantSuccess(BaseModel):
    trace: dict[str, Any] = Field(
        default_factory=dict,
        description="Router trace headers (x-aap-*, x-request-id, x-router-trace).",
    )
    response: dict[str, Any] = Field(description="Parsed JSON body from the router chat API.")


class CompareVariantFailure(BaseModel):
    error: str = Field(description="Error message when this variant's router call failed.")


class PlaygroundCompareOutput(BaseModel):
    """Shape of PlaygroundRunResponse.output when mode=compare and status is completed/failed."""

    variants: list[CompareVariantSuccess | CompareVariantFailure] = Field(
        min_length=1,
        description=(
            "One entry per artifact ref, in request order. Each variant uses the same "
            "model_alias, variables, and merged/overridden messages."
        ),
    )


class PlaygroundRunResponse(BaseModel):
    run_id: UUID
    mode: PlaygroundMode
    status: str
    resolved_revision_ids: list[UUID]
    model_alias: str
    router_trace: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] | PlaygroundCompareOutput | None = Field(
        default=None,
        description=(
            "Mode-specific payload. For compare, matches PlaygroundCompareOutput "
            "(variants array with trace/response or error per slot)."
        ),
    )
    error_message: str | None = None


class PlaygroundRunStatusOut(BaseModel):
    run_id: UUID
    status: str
    mode: str
    resolved_revision_ids: list[UUID]
    model_alias: str | None = None
    router_request_id: str | None = None
    router_trace: dict[str, Any] = Field(default_factory=dict)
    input_digest: str | None = None
    output_digest: str | None = None
    error_message: str | None = None


class PlaygroundCancelResponse(BaseModel):
    run_id: UUID
    status: str
    cancelled: bool
